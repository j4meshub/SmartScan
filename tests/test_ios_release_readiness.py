from __future__ import annotations

import copy
import plistlib
from pathlib import Path

import yaml

from tools.validate_ios_release import validate_draft, validate_release

ROOT = Path(__file__).parents[1]


def test_committed_ios_release_draft_is_valid() -> None:
    assert validate_draft(ROOT) == []


def test_release_gate_rejects_placeholders_missing_secrets_and_screenshots() -> None:
    errors = validate_release(ROOT, environ={})

    assert any("占位值" in error for error in errors)
    assert any("缺少发布环境变量" in error for error in errors)
    assert any("正式发布需要 1 至 10 张截图" in error for error in errors)
    assert any("Bundle ID" in error for error in errors)


def test_draft_rejects_metadata_over_limit(tmp_path: Path) -> None:
    root = _copy_release_fixture(tmp_path)
    subtitle = root / "apps" / "ios" / "release" / "metadata" / "en-US" / "subtitle.txt"
    subtitle.write_text("x" * 31, encoding="utf-8")

    assert any("subtitle.txt 超过 30" in error for error in validate_draft(root))


def test_draft_rejects_committed_review_credential_value(tmp_path: Path) -> None:
    root = _copy_release_fixture(tmp_path)
    path = root / "apps" / "ios" / "release" / "release-config.example.yml"
    config = yaml.safe_load(path.read_text(encoding="utf-8"))
    config["review_account"]["password"] = "do-not-commit"
    path.write_text(yaml.safe_dump(config, allow_unicode=True, sort_keys=False), encoding="utf-8")

    assert any("不允许保存凭据值" in error for error in validate_draft(root))


def test_privacy_manifest_declares_no_tracking_and_current_data_types() -> None:
    path = ROOT / "apps" / "ios" / "SmartScan" / "PrivacyInfo.xcprivacy"
    with path.open("rb") as handle:
        manifest = plistlib.load(handle)

    assert manifest["NSPrivacyTracking"] is False
    assert manifest["NSPrivacyTrackingDomains"] == []
    assert len(manifest["NSPrivacyCollectedDataTypes"]) == 5


def _copy_release_fixture(tmp_path: Path) -> Path:
    root = tmp_path / "repository"
    release_target = root / "apps" / "ios" / "release"
    release_target.mkdir(parents=True)
    source = ROOT / "apps" / "ios" / "release"
    for path in source.rglob("*"):
        if path.is_file():
            target = release_target / path.relative_to(source)
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(path.read_bytes())

    smartscan_target = root / "apps" / "ios" / "SmartScan"
    smartscan_target.mkdir(parents=True)
    (smartscan_target / "PrivacyInfo.xcprivacy").write_bytes(
        (ROOT / "apps" / "ios" / "SmartScan" / "PrivacyInfo.xcprivacy").read_bytes()
    )
    project = copy.deepcopy(
        yaml.safe_load((ROOT / "apps" / "ios" / "project.yml").read_text(encoding="utf-8"))
    )
    (root / "apps" / "ios" / "project.yml").write_text(
        yaml.safe_dump(project, allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    return root
