"""校验 Android 正式候选 APK、上一版本兼容证据和签名更新渠道。"""

from __future__ import annotations

import argparse
import base64
import hashlib
import json
import re
import subprocess
from collections.abc import Callable, Sequence
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import yaml
from cryptography.exceptions import InvalidSignature
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec

ROOT = Path(__file__).resolve().parents[1]
CONFIG = ROOT / "apps" / "android" / "release" / "release-config.example.yml"
GRADLE = ROOT / "apps" / "android" / "app" / "build.gradle.kts"
GITLAB = ROOT / ".gitlab" / "ci" / "android-release.yml"
SHA256 = re.compile(r"^[a-f0-9]{64}$")
VERSION_NAME = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


class AndroidReleaseError(ValueError):
    """Android 发布候选未满足失败关闭要求。"""


@dataclass(frozen=True)
class ApkIdentity:
    package_name: str
    version_code: int
    version_name: str
    certificate_sha256: str
    apk_sha256: str
    size_bytes: int


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise AndroidReleaseError(message)


def load_release_config(path: Path = CONFIG) -> dict[str, Any]:
    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, yaml.YAMLError) as exc:
        raise AndroidReleaseError("无法读取 Android 发布配置") from exc
    _require(isinstance(data, dict) and data.get("schema_version") == 1, "发布配置版本无效")
    required = {
        "package_name",
        "generic_package_name",
        "apk_file_name",
        "manifest_file_name",
        "signature_file_name",
        "channel_path",
        "minimum_previous_versions",
        "maximum_apk_size_bytes",
    }
    _require(set(data) == required | {"schema_version"}, "发布配置字段集合无效")
    _require(data["package_name"] == "com.smartscan.app", "Android 正式包名未冻结")
    _require(data["channel_path"] == "public/android", "更新渠道目录必须固定")
    _require(
        isinstance(data["minimum_previous_versions"], int)
        and not isinstance(data["minimum_previous_versions"], bool)
        and data["minimum_previous_versions"] >= 1,
        "必须验证至少一个上一稳定版本",
    )
    _require(
        isinstance(data["maximum_apk_size_bytes"], int)
        and not isinstance(data["maximum_apk_size_bytes"], bool)
        and 0 < data["maximum_apk_size_bytes"] <= 500 * 1024 * 1024,
        "APK 大小上限无效",
    )
    for key in (
        "generic_package_name",
        "apk_file_name",
        "manifest_file_name",
        "signature_file_name",
    ):
        _require(isinstance(data[key], str) and data[key] and "/" not in data[key], f"{key} 无效")
    return data


def validate_draft(root: Path = ROOT) -> list[str]:
    errors: list[str] = []
    try:
        load_release_config(root / "apps" / "android" / "release" / "release-config.example.yml")
    except AndroidReleaseError as exc:
        errors.append(str(exc))
    gradle = (root / "apps" / "android" / "app" / "build.gradle.kts").read_text(encoding="utf-8")
    for token in (
        "SMARTSCAN_VERSION_CODE",
        "SMARTSCAN_VERSION_NAME",
        "SMARTSCAN_ANDROID_KEYSTORE_FILE",
        "SMARTSCAN_ANDROID_KEYSTORE_PASSWORD",
        "SMARTSCAN_ANDROID_KEY_ALIAS",
        "SMARTSCAN_ANDROID_KEY_PASSWORD",
        "enableV2Signing = true",
        "enableV3Signing = true",
    ):
        if token not in gradle:
            errors.append(f"Gradle 缺少发布门禁：{token}")
    gitlab_path = root / ".gitlab" / "ci" / "android-release.yml"
    if not gitlab_path.is_file():
        errors.append("缺少 GitLab Android 发布流水线")
    else:
        gitlab = gitlab_path.read_text(encoding="utf-8")
        for token in (
            "CI_COMMIT_REF_PROTECTED",
            "@sha256:",
            "SMARTSCAN_ANDROID_PREVIOUS_VERSION_NAME",
            "validate_android_release.py configuration",
            "validate_android_release.py candidate",
            "android_update_manifest.py",
            "packages/generic",
            "public/android",
            "public/index.html",
            "validate_android_release.py channel",
            "pages:",
        ):
            if token not in gitlab:
                errors.append(f"GitLab 发布流水线缺少门禁：{token}")
    return errors


def _safe_https_url(value: str) -> Any:
    parsed = urlsplit(value)
    _require(
        parsed.scheme == "https"
        and parsed.hostname
        and not parsed.username
        and not parsed.password
        and not parsed.query
        and not parsed.fragment,
        "正式地址必须是不含凭据、查询参数和片段的 HTTPS URL",
    )
    return parsed


def validate_build_configuration(
    *,
    version_code: int,
    version_name: str,
    previous_version_name: str,
    minimum_supported_version_code: int,
    api_base_url: str,
    manifest_url: str,
    signature_url: str,
    public_key_base64: str,
) -> dict[str, Any]:
    """验证编译前公开参数，避免产出静默关闭更新能力的正式 APK。"""

    _require(version_code > 0, "versionCode 必须为正整数")
    _require(VERSION_NAME.fullmatch(version_name) is not None, "发布版本名称格式无效")
    _require(VERSION_NAME.fullmatch(previous_version_name) is not None, "上一版本名称格式无效")
    _require(previous_version_name != version_name, "上一版本不能与当前版本相同")
    _require(
        0 < minimum_supported_version_code <= version_code,
        "最低支持版本必须为正整数且不能高于发布版本",
    )
    api = _safe_https_url(api_base_url)
    manifest = _safe_https_url(manifest_url)
    signature = _safe_https_url(signature_url)
    _require(api_base_url.endswith("/"), "API 地址必须以斜杠结尾")
    _require(manifest.path.endswith("/android/latest.json"), "更新清单路径必须固定")
    _require(signature.path == f"{manifest.path}.sig", "更新清单与签名路径不匹配")
    _require(
        (manifest.scheme, manifest.netloc) == (signature.scheme, signature.netloc),
        "更新清单与签名必须使用同一来源",
    )
    try:
        public_der = base64.b64decode(public_key_base64, validate=True)
        key = serialization.load_der_public_key(public_der)
    except Exception as exc:
        raise AndroidReleaseError("更新清单公钥编码无效") from exc
    _require(
        isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1),
        "更新清单必须使用 ECDSA P-256 公钥",
    )
    return {
        "schema_version": 1,
        "status": "success",
        "version_code": version_code,
        "version_name": version_name,
        "previous_version_name": previous_version_name,
        "minimum_supported_version_code": minimum_supported_version_code,
        "api_host": api.hostname,
        "channel_host": manifest.hostname,
        "secrets_included": False,
    }


def _default_runner(command: Sequence[str]) -> str:
    result = subprocess.run(command, check=True, capture_output=True, text=True)
    return f"{result.stdout}\n{result.stderr}"


def inspect_apk(
    apk: Path,
    *,
    apkanalyzer: str = "apkanalyzer",
    apksigner: str = "apksigner",
    runner: Callable[[Sequence[str]], str] = _default_runner,
) -> ApkIdentity:
    _require(apk.is_file() and not apk.is_symlink(), "APK 必须是普通文件且不能是符号链接")
    size = apk.stat().st_size
    _require(0 < size <= 500 * 1024 * 1024, "APK 大小超出上限")
    package_name = runner([apkanalyzer, "manifest", "application-id", str(apk)]).strip()
    version_code_text = runner([apkanalyzer, "manifest", "version-code", str(apk)]).strip()
    version_name = runner([apkanalyzer, "manifest", "version-name", str(apk)]).strip()
    try:
        version_code = int(version_code_text)
    except ValueError as exc:
        raise AndroidReleaseError("APK versionCode 无效") from exc
    signature_output = runner([apksigner, "verify", "--verbose", "--print-certs", str(apk)])
    for scheme in ("v2", "v3"):
        _require(
            re.search(
                rf"Verified using {scheme} scheme \(APK Signature Scheme {scheme}\):\s*true",
                signature_output,
                re.IGNORECASE,
            )
            is not None,
            f"APK 未通过 {scheme} 签名方案校验",
        )
    matches = re.findall(
        r"Signer #\d+ certificate SHA-256 digest:\s*([0-9A-Fa-f:]{64,95})",
        signature_output,
    )
    normalized = {value.replace(":", "").lower() for value in matches}
    _require(
        len(normalized) == 1 and SHA256.fullmatch(next(iter(normalized), "")) is not None,
        "APK 必须只有一个当前签名证书",
    )
    digest = _sha256_file(apk)
    return ApkIdentity(
        package_name, version_code, version_name, next(iter(normalized)), digest, size
    )


def validate_candidate(
    apk: Path,
    previous_apks: Sequence[Path],
    *,
    expected_version_code: int,
    expected_version_name: str,
    expected_certificate_sha256: str,
    config_path: Path = CONFIG,
    runner: Callable[[Sequence[str]], str] = _default_runner,
) -> dict[str, Any]:
    config = load_release_config(config_path)
    _require(len(previous_apks) >= config["minimum_previous_versions"], "缺少上一稳定 APK 兼容证据")
    _require(VERSION_NAME.fullmatch(expected_version_name) is not None, "发布版本名称格式无效")
    certificate = expected_certificate_sha256.lower()
    _require(SHA256.fullmatch(certificate) is not None, "发布证书摘要无效")
    current = inspect_apk(apk, runner=runner)
    _require(current.package_name == config["package_name"], "候选 APK 包名不匹配")
    _require(current.version_code == expected_version_code, "候选 APK versionCode 不匹配")
    _require(current.version_name == expected_version_name, "候选 APK versionName 不匹配")
    _require(current.certificate_sha256 == certificate, "候选 APK 发布证书不匹配")
    _require(current.size_bytes <= config["maximum_apk_size_bytes"], "候选 APK 超过发布大小上限")
    previous: list[ApkIdentity] = []
    for path in previous_apks:
        identity = inspect_apk(path, runner=runner)
        _require(identity.package_name == current.package_name, "上一稳定 APK 包名不匹配")
        _require(
            identity.certificate_sha256 == current.certificate_sha256, "上一稳定 APK 证书不匹配"
        )
        _require(identity.version_code < current.version_code, "候选版本必须高于上一稳定版本")
        previous.append(identity)
    _require(len({item.version_code for item in previous}) == len(previous), "上一版本证据重复")
    return {
        "schema_version": 1,
        "status": "success",
        "candidate": asdict(current),
        "previous_versions": [
            asdict(item) for item in sorted(previous, key=lambda item: item.version_code)
        ],
        "secrets_included": False,
    }


def validate_channel(
    manifest_path: Path,
    signature_path: Path,
    public_key_base64: str,
    candidate: ApkIdentity,
) -> dict[str, Any]:
    _require(
        manifest_path.is_file()
        and not manifest_path.is_symlink()
        and 0 < manifest_path.stat().st_size <= 64 * 1024,
        "更新清单必须是大小受限的普通文件",
    )
    _require(
        signature_path.is_file()
        and not signature_path.is_symlink()
        and 0 < signature_path.stat().st_size <= 4096,
        "更新清单签名必须是大小受限的普通文件",
    )
    payload = manifest_path.read_bytes()
    try:
        signature = base64.b64decode(
            signature_path.read_text(encoding="ascii").strip(), validate=True
        )
        public_der = base64.b64decode(public_key_base64, validate=True)
        key = serialization.load_der_public_key(public_der)
    except Exception as exc:
        raise AndroidReleaseError("更新清单公钥或签名编码无效") from exc
    _require(
        isinstance(key, ec.EllipticCurvePublicKey) and isinstance(key.curve, ec.SECP256R1),
        "更新清单必须使用 ECDSA P-256 公钥",
    )
    try:
        key.verify(signature, payload, ec.ECDSA(hashes.SHA256()))
    except InvalidSignature as exc:
        raise AndroidReleaseError("更新清单签名无效") from exc
    try:
        manifest = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise AndroidReleaseError("更新清单 JSON 无效") from exc
    _require(manifest.get("schema_version") == 1, "更新清单版本无效")
    comparisons = {
        "package_name": candidate.package_name,
        "version_code": candidate.version_code,
        "version_name": candidate.version_name,
        "apk_sha256": candidate.apk_sha256,
        "apk_size_bytes": candidate.size_bytes,
        "apk_signing_certificate_sha256": candidate.certificate_sha256,
    }
    for key_name, expected in comparisons.items():
        _require(manifest.get(key_name) == expected, f"更新清单与候选 APK 不一致：{key_name}")
    minimum_supported = manifest.get("minimum_supported_version_code")
    _require(
        isinstance(minimum_supported, int)
        and not isinstance(minimum_supported, bool)
        and 0 < minimum_supported <= candidate.version_code,
        "更新清单最低支持版本无效",
    )
    try:
        published_at = datetime.fromisoformat(str(manifest.get("published_at", "")))
    except ValueError as exc:
        raise AndroidReleaseError("更新清单发布时间无效") from exc
    _require(published_at.tzinfo is not None, "更新清单发布时间必须包含时区")
    try:
        _safe_https_url(str(manifest.get("apk_url", "")))
    except AndroidReleaseError as exc:
        raise AndroidReleaseError("更新 APK 地址无效") from exc
    return {
        "schema_version": 1,
        "status": "success",
        "manifest_sha256": hashlib.sha256(payload).hexdigest(),
        "candidate_apk_sha256": candidate.apk_sha256,
        "secrets_included": False,
    }


def validate_channel_files(
    apk: Path,
    manifest_path: Path,
    signature_path: Path,
    public_key_base64: str,
    *,
    expected_version_name: str | None = None,
    runner: Callable[[Sequence[str]], str] = _default_runner,
) -> dict[str, Any]:
    """从实包提取身份，再校验准备发布或回滚的原始频道文件。"""

    candidate = inspect_apk(apk, runner=runner)
    if expected_version_name is not None:
        _require(VERSION_NAME.fullmatch(expected_version_name) is not None, "期望版本名称格式无效")
        _require(candidate.version_name == expected_version_name, "制品仓库版本与 APK 不匹配")
    return validate_channel(manifest_path, signature_path, public_key_base64, candidate)


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _write_report(path: Path, payload: dict[str, Any]) -> None:
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
    parser = argparse.ArgumentParser(description="校验 SmartScan Android 发布候选")
    subparsers = parser.add_subparsers(dest="mode")
    configuration = subparsers.add_parser("configuration")
    configuration.add_argument("--version-code", required=True, type=int)
    configuration.add_argument("--version-name", required=True)
    configuration.add_argument("--previous-version-name", required=True)
    configuration.add_argument("--minimum-supported-version-code", required=True, type=int)
    configuration.add_argument("--api-base-url", required=True)
    configuration.add_argument("--manifest-url", required=True)
    configuration.add_argument("--signature-url", required=True)
    configuration.add_argument("--public-key-base64", required=True)
    archive_version = subparsers.add_parser("archive-version")
    archive_version.add_argument("--version-name", required=True)
    candidate = subparsers.add_parser("candidate")
    candidate.add_argument("--apk", required=True, type=Path)
    candidate.add_argument("--previous-apk", required=True, action="append", type=Path)
    candidate.add_argument("--version-code", required=True, type=int)
    candidate.add_argument("--version-name", required=True)
    candidate.add_argument("--certificate-sha256", required=True)
    candidate.add_argument("--report", required=True, type=Path)
    channel = subparsers.add_parser("channel")
    channel.add_argument("--apk", required=True, type=Path)
    channel.add_argument("--manifest", required=True, type=Path)
    channel.add_argument("--signature", required=True, type=Path)
    channel.add_argument("--public-key-base64", required=True)
    channel.add_argument("--expected-version-name", required=True)
    channel.add_argument("--report", required=True, type=Path)
    args = parser.parse_args()
    if args.mode is None:
        errors = validate_draft()
        if errors:
            raise SystemExit("Android 发布草稿校验失败：\n- " + "\n- ".join(errors))
        print("Android 发布草稿校验通过；正式签名、上一版本和真机升级仍由发布门禁检查。")
        return 0
    if args.mode == "configuration":
        report = validate_build_configuration(
            version_code=args.version_code,
            version_name=args.version_name,
            previous_version_name=args.previous_version_name,
            minimum_supported_version_code=args.minimum_supported_version_code,
            api_base_url=args.api_base_url,
            manifest_url=args.manifest_url,
            signature_url=args.signature_url,
            public_key_base64=args.public_key_base64,
        )
        print(json.dumps(report, ensure_ascii=False))
        return 0
    if args.mode == "archive-version":
        if VERSION_NAME.fullmatch(args.version_name) is None:
            raise SystemExit("归档版本名称格式无效")
        print(
            json.dumps({"status": "success", "version_name": args.version_name}, ensure_ascii=False)
        )
        return 0
    if args.mode == "candidate":
        report = validate_candidate(
            args.apk,
            args.previous_apk,
            expected_version_code=args.version_code,
            expected_version_name=args.version_name,
            expected_certificate_sha256=args.certificate_sha256,
        )
        summary = {"status": "success", "version_code": args.version_code}
    else:
        report = validate_channel_files(
            args.apk,
            args.manifest,
            args.signature,
            args.public_key_base64,
            expected_version_name=args.expected_version_name,
        )
        summary = {"status": "success", "manifest_sha256": report["manifest_sha256"]}
    _write_report(args.report, report)
    print(json.dumps(summary, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
