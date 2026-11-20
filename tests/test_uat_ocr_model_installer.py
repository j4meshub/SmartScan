from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import pytest

from deploy.ops.smartscan_uat_ocr_model import (
    InstallError,
    install_fixed,
    status_fixed,
    verify_tree,
)


def _package(root: Path) -> None:
    files: dict[str, dict[str, object]] = {}
    for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"):
        path = root / directory / "inference.pdiparams"
        path.parent.mkdir(parents=True)
        value = directory.encode()
        path.write_bytes(value)
        files[path.relative_to(root).as_posix()] = {
            "sha256": hashlib.sha256(value).hexdigest(),
            "size": len(value),
        }
    evidence: dict[str, dict[str, object]] = {}
    for name in (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "UPSTREAM_MODEL_DESCRIPTION.md",
        "source-lock.json",
    ):
        value = name.encode()
        (root / name).write_bytes(value)
        evidence[name] = {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    manifest = {
        "schema_version": 1,
        "artifact_kind": "smartscan-offline-ocr-models",
        "artifact_version": "PP-OCRv6-small-v1",
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "license": "Apache-2.0",
        "text_detection_dir": "PP-OCRv6_small_det",
        "text_recognition_dir": "PP-OCRv6_small_rec",
        "files": {name: metadata["sha256"] for name, metadata in files.items()},
        "file_metadata": files,
        "evidence_files": evidence,
    }
    (root / "manifest.json").write_text(json.dumps(manifest), encoding="utf-8")


def test_fixed_installer_installs_once_and_verifies(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "stage"
    target = tmp_path / "target"
    stage.mkdir()
    target.mkdir()
    _package(stage)
    monkeypatch.setattr(os, "chown", lambda *_args: None, raising=False)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    result = install_fixed(stage, target, deploy_uid=uid, target_uid=uid)
    assert result["status"] == "passed"
    assert verify_tree(target, installed=False)["status"] == "passed"
    with pytest.raises(InstallError, match="target_not_empty"):
        install_fixed(stage, target, deploy_uid=uid, target_uid=uid)


@pytest.mark.parametrize("failure", ["business_file", "tamper", "symlink"])
def test_fixed_installer_rejects_abnormal_objects(
    tmp_path: Path, failure: str, monkeypatch: pytest.MonkeyPatch
) -> None:
    stage = tmp_path / "stage"
    target = tmp_path / "target"
    stage.mkdir()
    target.mkdir()
    _package(stage)
    monkeypatch.setattr(os, "chown", lambda *_args: None, raising=False)
    if failure == "business_file":
        (target / "business.dat").write_bytes(b"data")
    elif failure == "tamper":
        (stage / "PP-OCRv6_small_det" / "inference.pdiparams").write_bytes(b"tamper")
    else:
        victim = stage / "LICENSE"
        victim.unlink()
        try:
            victim.symlink_to(stage / "source-lock.json")
        except OSError:
            pytest.skip("当前平台不允许创建测试符号链接")
    with pytest.raises(InstallError):
        uid = os.getuid() if hasattr(os, "getuid") else 0
        install_fixed(stage, target, deploy_uid=uid, target_uid=uid)


def test_status_never_modifies_partial_install(tmp_path: Path) -> None:
    target = tmp_path / "target"
    target.mkdir()
    (target / "partial").write_bytes(b"evidence")
    assert status_fixed(target) == {
        "status": "partial_or_invalid",
        "installed": False,
        "reason": "manifest_missing",
    }
    assert (target / "partial").read_bytes() == b"evidence"
