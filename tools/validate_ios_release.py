"""校验 iOS App Store 准备资产，不读取或输出任何真实密钥。"""

from __future__ import annotations

import argparse
import os
import plistlib
import re
import sys
from pathlib import Path
from typing import Any

import yaml
from PIL import Image

ROOT = Path(__file__).parents[1]
IOS_ROOT = ROOT / "apps" / "ios"
RELEASE_ROOT = IOS_ROOT / "release"
CONFIG_PATH = RELEASE_ROOT / "release-config.example.yml"
SCREENSHOTS_PATH = RELEASE_ROOT / "screenshots.yml"
METADATA_LIMITS = {
    "name.txt": 30,
    "subtitle.txt": 30,
    "promotional_text.txt": 170,
    "description.txt": 4000,
    "release_notes.txt": 4000,
}
REQUIRED_METADATA = {*METADATA_LIMITS, "keywords.txt"}
PLACEHOLDER_MARKERS = (".invalid", "_REQUIRED", "${")
ENV_NAME_PATTERN = re.compile(r"^[A-Z][A-Z0-9_]+$")


def load_yaml(path: Path) -> dict[str, Any]:
    value = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError(f"{path} 顶层必须是对象")
    return value


def validate_draft(root: Path = ROOT) -> list[str]:
    """返回草稿资产错误；占位外部参数在该模式下是合法的。"""

    ios_root = root / "apps" / "ios"
    release_root = ios_root / "release"
    errors: list[str] = []
    try:
        config = load_yaml(release_root / "release-config.example.yml")
        screenshots = load_yaml(release_root / "screenshots.yml")
    except (OSError, TypeError, yaml.YAMLError) as exc:
        return [str(exc)]

    if config.get("schema_version") != 1:
        errors.append("发布配置 schema_version 必须为 1")
    locales = config.get("locales")
    if locales != ["en-US", "zh-Hans"]:
        errors.append("发布配置必须且只能声明 en-US 与 zh-Hans")
        locales = ["en-US", "zh-Hans"]

    for locale in locales:
        metadata_dir = release_root / "metadata" / locale
        present = {path.name for path in metadata_dir.glob("*.txt")}
        missing = REQUIRED_METADATA - present
        if missing:
            errors.append(f"{locale} 缺少元数据：{', '.join(sorted(missing))}")
        for filename in REQUIRED_METADATA & present:
            content = (metadata_dir / filename).read_text(encoding="utf-8").strip()
            if not content:
                errors.append(f"{locale}/{filename} 不能为空")
            if filename in METADATA_LIMITS and len(content) > METADATA_LIMITS[filename]:
                errors.append(f"{locale}/{filename} 超过 {METADATA_LIMITS[filename]} 个字符")
            if filename == "keywords.txt" and len(content.encode("utf-8")) > 100:
                errors.append(f"{locale}/keywords.txt 超过 100 字节")

        review_notes = release_root / "review-notes" / f"{locale}.md"
        if not review_notes.is_file() or not review_notes.read_text(encoding="utf-8").strip():
            errors.append(f"缺少 {locale} 审核说明")

    errors.extend(_validate_environment_references(config))
    errors.extend(_validate_screenshot_manifest(screenshots, release_root, require_files=False))
    errors.extend(_validate_privacy_manifest(ios_root / "SmartScan" / "PrivacyInfo.xcprivacy"))
    errors.extend(_validate_project_links(ios_root / "project.yml"))
    return errors


def validate_release(root: Path = ROOT, environ: dict[str, str] | None = None) -> list[str]:
    """执行正式发布门禁；仅检查环境变量是否存在，不读取或打印其值。"""

    errors = validate_draft(root)
    release_root = root / "apps" / "ios" / "release"
    try:
        config = load_yaml(release_root / "release-config.example.yml")
        screenshots = load_yaml(release_root / "screenshots.yml")
    except (OSError, TypeError, yaml.YAMLError):
        return errors

    values = [
        config.get("product", {}).get("bundle_id", ""),
        config.get("product", {}).get("app_store_id", ""),
        config.get("product", {}).get("apple_team_id", ""),
        config.get("product", {}).get("sku", ""),
        *config.get("services", {}).values(),
    ]
    for value in values:
        rendered = str(value)
        if not rendered or any(marker in rendered for marker in PLACEHOLDER_MARKERS):
            errors.append(f"正式发布参数仍为占位值：{_safe_parameter_name(config, value)}")

    bundle_id = str(config.get("product", {}).get("bundle_id", ""))
    if bundle_id.endswith(".dev"):
        errors.append("正式 Bundle ID 不能使用 .dev 占位后缀")

    env = environ if environ is not None else os.environ
    for name in _environment_names(config):
        if not env.get(name):
            errors.append(f"缺少发布环境变量：{name}")

    errors.extend(_validate_screenshot_manifest(screenshots, release_root, require_files=True))
    return errors


def _validate_environment_references(config: dict[str, Any]) -> list[str]:
    errors: list[str] = []
    for section_name in ("review_account", "signing"):
        section = config.get(section_name)
        if not isinstance(section, dict):
            errors.append(f"缺少 {section_name} 配置")
            continue
        for key, value in section.items():
            if key.endswith("_environment"):
                if not isinstance(value, str) or not ENV_NAME_PATTERN.fullmatch(value):
                    errors.append(f"{section_name}.{key} 必须只引用环境变量名")
            elif key not in {"role"}:
                errors.append(f"{section_name}.{key} 不允许保存凭据值")
    if config.get("review_account", {}).get("role") != "user":
        errors.append("审核账号必须使用普通 user 角色")
    return errors


def _environment_names(config: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for section_name in ("review_account", "signing"):
        for key, value in config.get(section_name, {}).items():
            if key.endswith("_environment") and isinstance(value, str):
                names.append(value)
    return names


def _validate_screenshot_manifest(
    screenshots: dict[str, Any], release_root: Path, *, require_files: bool
) -> list[str]:
    errors: list[str] = []
    if screenshots.get("schema_version") != 1:
        errors.append("截图清单 schema_version 必须为 1")
    devices = screenshots.get("devices", {})
    locales = screenshots.get("locales", {})
    required_devices = {"iphone_6_9", "ipad_13"}
    if set(devices) != required_devices:
        errors.append("截图设备必须覆盖 iphone_6_9 与 ipad_13")
    if set(locales) != {"en-US", "zh-Hans"}:
        errors.append("截图语言必须覆盖 en-US 与 zh-Hans")

    for locale, details in locales.items():
        scenes = details.get("scenes", []) if isinstance(details, dict) else []
        if len(scenes) < 5 or len(scenes) != len(set(scenes)):
            errors.append(f"{locale} 必须包含至少 5 个不重复截图场景")
        for device_name in required_devices:
            files = details.get(device_name, []) if isinstance(details, dict) else []
            if require_files and not 1 <= len(files) <= 10:
                errors.append(f"{locale}/{device_name} 正式发布需要 1 至 10 张截图")
            accepted = {
                tuple(size)
                for size in devices.get(device_name, {}).get("accepted_portrait_sizes", [])
            }
            for relative in files:
                path = release_root / relative
                if not path.is_file():
                    errors.append(f"截图不存在：{relative}")
                    continue
                try:
                    with Image.open(path) as image:
                        if image.format not in {"JPEG", "PNG"}:
                            errors.append(f"截图格式必须为 JPEG 或 PNG：{relative}")
                        if image.size not in accepted:
                            errors.append(f"截图尺寸不符合 {device_name}：{relative}")
                        if image.mode in {"RGBA", "LA"} or "transparency" in image.info:
                            errors.append(f"截图不能包含透明通道：{relative}")
                except OSError:
                    errors.append(f"无法读取截图：{relative}")
    return errors


def _validate_privacy_manifest(path: Path) -> list[str]:
    errors: list[str] = []
    try:
        with path.open("rb") as handle:
            manifest = plistlib.load(handle)
    except (OSError, plistlib.InvalidFileException) as exc:
        return [f"隐私清单无效：{exc}"]
    if manifest.get("NSPrivacyTracking") is not False:
        errors.append("当前版本必须明确声明不跟踪")
    if manifest.get("NSPrivacyTrackingDomains") != []:
        errors.append("当前版本不得声明跟踪域名")
    types = {
        item.get("NSPrivacyCollectedDataType")
        for item in manifest.get("NSPrivacyCollectedDataTypes", [])
    }
    expected = {
        "NSPrivacyCollectedDataTypePhoneNumber",
        "NSPrivacyCollectedDataTypeUserID",
        "NSPrivacyCollectedDataTypePhotosorVideos",
        "NSPrivacyCollectedDataTypeOtherUserContent",
        "NSPrivacyCollectedDataTypeDeviceID",
    }
    if types != expected:
        errors.append("隐私清单收集类型与当前客户端数据流不一致")
    return errors


def _validate_project_links(path: Path) -> list[str]:
    project = load_yaml(path)
    settings = project.get("targets", {}).get("SmartScan", {}).get("settings", {}).get("base", {})
    keys = {"SMARTSCAN_PRIVACY_POLICY_URL", "SMARTSCAN_SUPPORT_URL"}
    return [f"project.yml 缺少 {key}" for key in keys if key not in settings]


def _safe_parameter_name(config: dict[str, Any], target: Any) -> str:
    for section_name in ("product", "services"):
        for key, value in config.get(section_name, {}).items():
            if value == target:
                return f"{section_name}.{key}"
    return "未知参数"


def main() -> int:
    parser = argparse.ArgumentParser(description="校验 iOS 审核与发布准备资产")
    parser.add_argument("--release", action="store_true", help="启用正式发布硬门禁")
    args = parser.parse_args()
    errors = validate_release() if args.release else validate_draft()
    if errors:
        print("iOS 发布准备校验失败：")
        for error in errors:
            print(f"- {error}")
        return 1
    if args.release:
        print("iOS 正式发布门禁通过。")
    else:
        print("iOS 发布草稿校验通过；正式参数、截图、签名和审核账号仍由 --release 门禁检查。")
    return 0


if __name__ == "__main__":
    sys.exit(main())
