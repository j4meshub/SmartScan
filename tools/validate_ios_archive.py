"""校验 iOS Archive、App Store 描述文件和导出的 IPA 实包。"""

from __future__ import annotations

import argparse
import hashlib
import json
import plistlib
import re
import zipfile
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from urllib.parse import urlsplit

MAX_IPA_SIZE_BYTES = 4 * 1024 * 1024 * 1024
MAX_IPA_UNCOMPRESSED_BYTES = 8 * 1024 * 1024 * 1024
VERSION_NAME = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")
BUILD_NUMBER = re.compile(r"^[1-9][0-9]*$")
TEAM_ID = re.compile(r"^[A-Z0-9]{10}$")
BUNDLE_ID = re.compile(r"^[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+$")


class IOSArchiveError(ValueError):
    """正式 iOS 制品未满足发布门禁。"""


@dataclass(frozen=True)
class IOSArchiveIdentity:
    bundle_id: str
    marketing_version: str
    build_number: str
    team_id: str
    signing_identity: str
    profile_uuid: str
    profile_name: str
    profile_expires_at: str
    ipa_sha256: str
    ipa_size_bytes: int
    xcode_version: str
    codesign_verified: bool


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise IOSArchiveError(message)


def _load_plist(path: Path, *, maximum_bytes: int = 4 * 1024 * 1024) -> dict:
    _require(path.is_file() and not path.is_symlink(), f"必须是普通 plist 文件：{path.name}")
    _require(0 < path.stat().st_size <= maximum_bytes, f"plist 大小无效：{path.name}")
    try:
        with path.open("rb") as handle:
            value = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        raise IOSArchiveError(f"无法读取 plist：{path.name}") from exc
    _require(isinstance(value, dict), f"plist 顶层必须是对象：{path.name}")
    return value


def _safe_https_url(value: str, name: str) -> None:
    parsed = urlsplit(value)
    _require(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment,
        f"{name} 必须是不含凭据、查询参数和片段的 HTTPS URL",
    )


def _safe_application_path(archive: Path, value: object) -> Path:
    _require(isinstance(value, str) and value, "Archive 缺少应用相对路径")
    relative = PurePosixPath(value)
    _require(not relative.is_absolute() and ".." not in relative.parts, "Archive 应用路径越界")
    application = archive.joinpath(*relative.parts)
    _require(application.resolve().is_relative_to(archive.resolve()), "Archive 应用路径越界")
    _require(application.is_dir() and not application.is_symlink(), "Archive 应用目录无效")
    return application


def _validate_app_info(
    info: dict,
    *,
    bundle_id: str,
    marketing_version: str,
    build_number: str,
    api_base_url: str,
    privacy_policy_url: str,
    support_url: str,
) -> None:
    expected = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleShortVersionString": marketing_version,
        "CFBundleVersion": build_number,
        "SMARTSCAN_API_BASE_URL": api_base_url,
        "SMARTSCAN_PRIVACY_POLICY_URL": privacy_policy_url,
        "SMARTSCAN_SUPPORT_URL": support_url,
        "SMARTSCAN_BACKGROUND_TASK_IDENTIFIER": f"{bundle_id}.upload",
    }
    for key, value in expected.items():
        _require(str(info.get(key, "")) == value, f"应用 Info.plist 不匹配：{key}")
    _require(
        info.get("BGTaskSchedulerPermittedIdentifiers") == [f"{bundle_id}.upload"],
        "后台任务标识必须跟随正式 Bundle ID",
    )


def _validate_profile(profile: dict, *, bundle_id: str, team_id: str) -> tuple[str, str, str]:
    teams = profile.get("TeamIdentifier")
    _require(teams == [team_id], "描述文件 TeamIdentifier 不匹配")
    _require(not profile.get("ProvisionedDevices"), "App Store 描述文件不得绑定测试设备")
    _require(profile.get("ProvisionsAllDevices") is not True, "不得使用企业分发描述文件")
    entitlements = profile.get("Entitlements")
    _require(isinstance(entitlements, dict), "描述文件缺少 Entitlements")
    _require(entitlements.get("get-task-allow") is False, "正式描述文件不得允许调试")
    _require(
        entitlements.get("com.apple.developer.team-identifier") == team_id,
        "描述文件 Team Entitlement 不匹配",
    )
    application_identifier = str(entitlements.get("application-identifier", ""))
    _require(
        application_identifier == f"{team_id}.{bundle_id}",
        "描述文件 App ID 不匹配",
    )
    uuid = str(profile.get("UUID", ""))
    name = str(profile.get("Name", ""))
    _require(uuid and name, "描述文件缺少 UUID 或名称")
    expiration = profile.get("ExpirationDate")
    _require(isinstance(expiration, datetime), "描述文件缺少有效期")
    comparable = expiration if expiration.tzinfo else expiration.replace(tzinfo=UTC)
    _require(comparable > datetime.now(UTC), "描述文件已经过期")
    return uuid, name, comparable.astimezone(UTC).isoformat()


def _validate_ipa(
    ipa: Path, expected_info: dict, expected_embedded_profile: bytes
) -> tuple[str, int]:
    _require(ipa.is_file() and not ipa.is_symlink(), "IPA 必须是普通文件")
    size = ipa.stat().st_size
    _require(0 < size <= MAX_IPA_SIZE_BYTES, "IPA 大小无效")
    try:
        with zipfile.ZipFile(ipa) as archive:
            members = archive.infolist()
            _require(members, "IPA 不能为空")
            total = 0
            info_members: list[zipfile.ZipInfo] = []
            profile_members: list[zipfile.ZipInfo] = []
            for member in members:
                path = PurePosixPath(member.filename)
                _require(
                    not path.is_absolute()
                    and ".." not in path.parts
                    and "\\" not in member.filename,
                    "IPA 包含越界路径",
                )
                total += member.file_size
                _require(total <= MAX_IPA_UNCOMPRESSED_BYTES, "IPA 解压后大小超出上限")
                if (
                    len(path.parts) == 3
                    and path.parts[0] == "Payload"
                    and path.parts[1].endswith(".app")
                ):
                    if path.parts[2] == "Info.plist":
                        info_members.append(member)
                    elif path.parts[2] == "embedded.mobileprovision":
                        profile_members.append(member)
            _require(len(info_members) == 1, "IPA 必须只包含一个顶层应用 Info.plist")
            _require(len(profile_members) == 1, "IPA 必须包含一个嵌入描述文件")
            ipa_info = plistlib.loads(archive.read(info_members[0]))
            _require(ipa_info == expected_info, "IPA 与 Archive 的应用 Info.plist 不一致")
            _require(
                archive.read(profile_members[0]) == expected_embedded_profile,
                "IPA 与 Archive 的嵌入描述文件不一致",
            )
    except (OSError, zipfile.BadZipFile, plistlib.InvalidFileException) as exc:
        raise IOSArchiveError("IPA 无法读取") from exc
    return _sha256_file(ipa), size


def validate_archive(
    *,
    archive: Path,
    ipa: Path,
    embedded_profile_plist: Path,
    bundle_id: str,
    marketing_version: str,
    build_number: str,
    team_id: str,
    api_base_url: str,
    privacy_policy_url: str,
    support_url: str,
    xcode_version: str,
    minimum_xcode_major: int,
    codesign_verified: bool,
) -> dict:
    _require(archive.is_dir() and not archive.is_symlink(), "Archive 目录无效")
    _require(BUNDLE_ID.fullmatch(bundle_id) is not None, "正式 Bundle ID 无效")
    _require(VERSION_NAME.fullmatch(marketing_version) is not None, "版本名称无效")
    _require(BUILD_NUMBER.fullmatch(build_number) is not None, "构建号无效")
    _require(TEAM_ID.fullmatch(team_id) is not None, "Apple Team ID 无效")
    for value, name in (
        (api_base_url, "API 地址"),
        (privacy_policy_url, "隐私政策地址"),
        (support_url, "支持地址"),
    ):
        _safe_https_url(value, name)
    version_match = re.search(r"(?:^|\s)Xcode\s+([0-9]+(?:\.[0-9]+)*)", xcode_version)
    _require(version_match is not None, "无法识别 Xcode 版本")
    _require(
        int(version_match.group(1).split(".")[0]) >= minimum_xcode_major, "Xcode 版本低于上传门禁"
    )
    _require(codesign_verified, "必须先通过 codesign 实包校验")

    archive_info = _load_plist(archive / "Info.plist")
    properties = archive_info.get("ApplicationProperties")
    _require(isinstance(properties, dict), "Archive 缺少 ApplicationProperties")
    application = _safe_application_path(archive, properties.get("ApplicationPath"))
    app_info = _load_plist(application / "Info.plist")
    _validate_app_info(
        app_info,
        bundle_id=bundle_id,
        marketing_version=marketing_version,
        build_number=build_number,
        api_base_url=api_base_url,
        privacy_policy_url=privacy_policy_url,
        support_url=support_url,
    )
    archive_expected = {
        "CFBundleIdentifier": bundle_id,
        "CFBundleShortVersionString": marketing_version,
        "CFBundleVersion": build_number,
        "Team": team_id,
    }
    for key, value in archive_expected.items():
        _require(str(properties.get(key, "")) == value, f"Archive 属性不匹配：{key}")
    signing_identity = str(properties.get("SigningIdentity", ""))
    _require("Distribution" in signing_identity, "Archive 未使用发行签名身份")

    profile = _load_plist(embedded_profile_plist, maximum_bytes=1024 * 1024)
    profile_uuid, profile_name, profile_expires_at = _validate_profile(
        profile, bundle_id=bundle_id, team_id=team_id
    )
    archive_profile = application / "embedded.mobileprovision"
    _require(
        archive_profile.is_file() and not archive_profile.is_symlink(),
        "Archive 缺少嵌入描述文件",
    )
    _require(
        0 < archive_profile.stat().st_size <= 1024 * 1024,
        "Archive 嵌入描述文件大小无效",
    )
    ipa_sha256, ipa_size = _validate_ipa(ipa, app_info, archive_profile.read_bytes())
    identity = IOSArchiveIdentity(
        bundle_id=bundle_id,
        marketing_version=marketing_version,
        build_number=build_number,
        team_id=team_id,
        signing_identity=signing_identity,
        profile_uuid=profile_uuid,
        profile_name=profile_name,
        profile_expires_at=profile_expires_at,
        ipa_sha256=ipa_sha256,
        ipa_size_bytes=ipa_size,
        xcode_version=version_match.group(1),
        codesign_verified=True,
    )
    return {"schema_version": 1, "status": "success", **asdict(identity), "secrets_included": False}


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_report(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp")
    try:
        temporary.write_text(
            json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n",
            encoding="utf-8",
        )
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 SmartScan iOS 正式 Archive 与 IPA")
    parser.add_argument("--archive", required=True, type=Path)
    parser.add_argument("--ipa", required=True, type=Path)
    parser.add_argument("--embedded-profile-plist", required=True, type=Path)
    parser.add_argument("--bundle-id", required=True)
    parser.add_argument("--marketing-version", required=True)
    parser.add_argument("--build-number", required=True)
    parser.add_argument("--team-id", required=True)
    parser.add_argument("--api-base-url", required=True)
    parser.add_argument("--privacy-policy-url", required=True)
    parser.add_argument("--support-url", required=True)
    parser.add_argument("--xcode-version", required=True)
    parser.add_argument("--minimum-xcode-major", required=True, type=int)
    parser.add_argument("--codesign-verified", action="store_true")
    parser.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    report = validate_archive(
        archive=args.archive,
        ipa=args.ipa,
        embedded_profile_plist=args.embedded_profile_plist,
        bundle_id=args.bundle_id,
        marketing_version=args.marketing_version,
        build_number=args.build_number,
        team_id=args.team_id,
        api_base_url=args.api_base_url,
        privacy_policy_url=args.privacy_policy_url,
        support_url=args.support_url,
        xcode_version=args.xcode_version,
        minimum_xcode_major=args.minimum_xcode_major,
        codesign_verified=args.codesign_verified,
    )
    _write_report(args.report, report)
    print(json.dumps({"status": "success", "ipa_sha256": report["ipa_sha256"]}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
