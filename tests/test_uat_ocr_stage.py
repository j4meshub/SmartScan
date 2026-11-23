from __future__ import annotations

import hashlib
import io
import json
import os
import shutil
import subprocess
import tarfile
from pathlib import Path

import pytest

from deploy.ops import smartscan_ocr_layer_contract as layer_contract
from deploy.ops.smartscan_ocr_layer_contract import LayerContractError
from deploy.ops.smartscan_uat_ocr_model import install_fixed
from deploy.ops.smartscan_uat_ocr_stage import StageError, stage_fixed, status_fixed, verify_fixed


def _package_files(*, bad_manifest: bool = False) -> dict[str, bytes]:
    files: dict[str, bytes] = {}
    metadata: dict[str, dict[str, object]] = {}
    for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"):
        for name in ("inference.json", "inference.pdiparams", "inference.yml"):
            relative = f"{directory}/{name}"
            value = relative.encode()
            files[relative] = value
            metadata[relative] = {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    evidence: dict[str, dict[str, object]] = {}
    for name in (
        "LICENSE",
        "THIRD_PARTY_NOTICES.md",
        "UPSTREAM_MODEL_DESCRIPTION.md",
        "source-lock.json",
    ):
        value = name.encode()
        files[name] = value
        evidence[name] = {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
    manifest = {
        "schema_version": 1,
        "artifact_kind": "wrong" if bad_manifest else "smartscan-offline-ocr-models",
        "artifact_version": "PP-OCRv6-small-v1",
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "license": "Apache-2.0",
        "text_detection_dir": "PP-OCRv6_small_det",
        "text_recognition_dir": "PP-OCRv6_small_rec",
        "files": {name: item["sha256"] for name, item in metadata.items()},
        "file_metadata": metadata,
        "evidence_files": evidence,
    }
    files["manifest.json"] = json.dumps(manifest).encode()
    return files


def _layer(
    path: Path, files: dict[str, bytes], *, extra: tarfile.TarInfo | None = None
) -> tuple[str, int]:
    with tarfile.open(path, mode="w:gz") as bundle:
        for name, value in files.items():
            item = tarfile.TarInfo(f"models/ocr/{name}")
            item.size = len(value)
            bundle.addfile(item, io.BytesIO(value))
        if extra is not None:
            bundle.addfile(extra, io.BytesIO(b"x") if extra.size else None)
    value = path.read_bytes()
    return hashlib.sha256(value).hexdigest(), len(value)


def _stage(
    layer: Path,
    staging: Path,
    digest: str,
    size: int,
    monkeypatch: pytest.MonkeyPatch,
) -> dict[str, object]:
    monkeypatch.setattr(os, "chown", lambda *_args: None, raising=False)
    staging.parent.parent.mkdir(parents=True, exist_ok=True)
    with tarfile.open(layer, mode="r:gz") as bundle:
        model_sizes = {
            member.name.removeprefix("models/ocr/"): member.size
            for member in bundle.getmembers()
            if member.name.removeprefix("models/ocr/") in layer_contract.MODEL_FILE_SIZES
        }
    monkeypatch.setattr(layer_contract, "MODEL_FILE_SIZES", model_sizes)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    return stage_fixed(
        layer,
        staging,
        expected_uid=uid,
        enforce_upload_permissions=False,
        root_uid=uid,
        expected_sha256=digest,
        expected_size=size,
    )


def test_stage_verifies_safe_layer_and_existing_installer_contract(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "layer.tar.gz"
    digest, size = _layer(layer, _package_files())
    staging = tmp_path / "models" / ".ocr-staging" / "PP-OCRv6-small-v1"
    result = _stage(layer, staging, digest, size, monkeypatch)
    assert result["staged"] is True
    uid = os.getuid() if hasattr(os, "getuid") else 0
    assert (
        verify_fixed(
            layer,
            staging,
            expected_uid=uid,
            enforce_upload_permissions=False,
            root_uid=uid,
            expected_sha256=digest,
            expected_size=size,
        )["status"]
        == "passed"
    )
    if os.name == "nt":
        pytest.skip("现有安装器的UID/GID门禁仅在Linux验证")
    target = tmp_path / "target"
    target.mkdir()
    assert install_fixed(staging, target, deploy_uid=uid, target_uid=uid)["status"] == "passed"
    with pytest.raises(StageError, match="staging_state_not_empty"):
        _stage(layer, staging, digest, size, monkeypatch)


@pytest.mark.skipif(os.name == "nt", reason="真实Layer端到端安装契约由Ubuntu Runner执行")
def test_real_fixed_layer_stages_and_matches_existing_installer(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    source = os.environ.get("SMARTSCAN_REAL_OCR_LAYER")
    if not source:
        pytest.skip("本地不下载真实Layer")
    layer = Path(source).resolve()
    assert layer.is_file()
    uid = os.getuid()
    monkeypatch.setattr(os, "chown", lambda *_args: None)
    staging = tmp_path / "models" / ".ocr-staging" / "PP-OCRv6-small-v1"
    staging.parent.parent.mkdir(parents=True)
    result = stage_fixed(
        layer,
        staging,
        expected_uid=uid,
        enforce_upload_permissions=False,
        root_uid=uid,
    )
    assert result["staged"] is True
    target = tmp_path / "installed"
    target.mkdir()
    installed = install_fixed(staging, target, deploy_uid=uid, target_uid=uid)
    assert installed["status"] == "passed"
    assert installed["artifact_version"] == "PP-OCRv6-small-v1"


@pytest.mark.parametrize(
    ("name", "kind"),
    [
        ("/absolute", tarfile.REGTYPE),
        ("models/ocr/../escape", tarfile.REGTYPE),
        ("models/ocr/link", tarfile.SYMTYPE),
        ("models/ocr/hard", tarfile.LNKTYPE),
        ("models/ocr/device", tarfile.CHRTYPE),
        ("models/ocr/fifo", tarfile.FIFOTYPE),
        ("models/ocr/extra", tarfile.REGTYPE),
    ],
)
def test_stage_rejects_unsafe_or_extra_tar_members(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    name: str,
    kind: bytes,
) -> None:
    layer = tmp_path / "layer.tar.gz"
    extra = tarfile.TarInfo(name)
    extra.type = kind
    extra.size = 1 if kind == tarfile.REGTYPE else 0
    digest, size = _layer(layer, _package_files(), extra=extra)
    staging = tmp_path / "staging"
    with pytest.raises(LayerContractError):
        _stage(layer, staging, digest, size, monkeypatch)
    assert not staging.exists()


def test_stage_rejects_duplicate_path(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    files = _package_files()
    layer = tmp_path / "layer.tar.gz"
    with tarfile.open(layer, mode="w:gz") as bundle:
        for name, value in files.items():
            item = tarfile.TarInfo(f"models/ocr/{name}")
            item.size = len(value)
            bundle.addfile(item, io.BytesIO(value))
        value = files["LICENSE"]
        duplicate = tarfile.TarInfo("models/ocr/LICENSE")
        duplicate.size = len(value)
        bundle.addfile(duplicate, io.BytesIO(value))
    raw = layer.read_bytes()
    with pytest.raises(LayerContractError):
        _stage(layer, tmp_path / "staging", hashlib.sha256(raw).hexdigest(), len(raw), monkeypatch)


def test_stage_rejects_symlink_upload_and_target(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "layer.tar.gz"
    digest, size = _layer(layer, _package_files())
    upload_link = tmp_path / "upload-link.tar.gz"
    staging = tmp_path / "models" / ".ocr-staging" / "PP-OCRv6-small-v1"
    staging.parent.parent.mkdir(parents=True)
    target = tmp_path / "target"
    target.mkdir()
    try:
        upload_link.symlink_to(layer)
        staging.parent.mkdir()
        staging.symlink_to(target, target_is_directory=True)
    except OSError:
        pytest.skip("当前平台不允许创建测试符号链接")
    with pytest.raises(LayerContractError, match="layer_file_invalid"):
        stage_fixed(
            upload_link,
            tmp_path / "another-stage",
            enforce_upload_permissions=False,
            expected_sha256=digest,
            expected_size=size,
        )
    with pytest.raises(StageError, match="staging_state_not_empty"):
        _stage(layer, staging, digest, size, monkeypatch)


def test_stage_preserves_partial_evidence_on_manifest_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "layer.tar.gz"
    digest, size = _layer(layer, _package_files(bad_manifest=True))
    staging = tmp_path / "staging"
    with pytest.raises(StageError, match="partial_stage_requires_separate_cleanup_authorization"):
        _stage(layer, staging, digest, size, monkeypatch)
    partial = staging.with_name(f"{staging.name}.partial")
    assert partial.is_dir()
    uid = os.getuid() if hasattr(os, "getuid") else 0
    assert (
        status_fixed(
            layer,
            staging,
            expected_uid=uid,
            enforce_upload_permissions=False,
            root_uid=uid,
            expected_sha256=digest,
            expected_size=size,
        )["staging"]
        == "partial_or_invalid"
    )


def test_stage_rejects_wrong_hash_size_and_corrupt_gzip(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "layer.tar.gz"
    layer.write_bytes(b"corrupt")
    with pytest.raises((LayerContractError, tarfile.TarError)):
        _stage(layer, tmp_path / "a", "0" * 64, len(layer.read_bytes()), monkeypatch)
    digest = hashlib.sha256(layer.read_bytes()).hexdigest()
    with pytest.raises((LayerContractError, tarfile.TarError)):
        _stage(layer, tmp_path / "b", digest, 1, monkeypatch)
    with pytest.raises((LayerContractError, tarfile.TarError)):
        _stage(layer, tmp_path / "c", digest, len(layer.read_bytes()), monkeypatch)


@pytest.mark.skipif(os.name == "nt", reason="POSIX权限仅在Linux执行")
def test_upload_requires_owner_and_mode_0600(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    layer = tmp_path / "layer.tar.gz"
    digest, size = _layer(layer, _package_files())
    layer.chmod(0o644)
    uid = os.getuid()
    staging = tmp_path / "models" / ".ocr-staging" / "PP-OCRv6-small-v1"
    staging.parent.parent.mkdir(parents=True)
    monkeypatch.setattr(
        layer_contract,
        "MODEL_FILE_SIZES",
        {name: len(name.encode()) for name in layer_contract.MODEL_FILE_SIZES},
    )
    with pytest.raises(LayerContractError, match="layer_mode_invalid"):
        stage_fixed(
            layer,
            staging,
            expected_uid=uid,
            enforce_upload_permissions=True,
            root_uid=uid,
            expected_sha256=digest,
            expected_size=size,
        )


def test_stage_assets_grant_only_three_exact_commands() -> None:
    root = Path(__file__).resolve().parents[1]
    executor = (root / "deploy/ops/smartscan-uat-ocr-stage").read_text(encoding="utf-8")
    sudoers = (root / "deploy/ops/smartscan-uat-ocr-stage.sudoers").read_text(encoding="utf-8")
    for helper in ("smartscan_uat_ocr_stage.py", "smartscan_ocr_layer_contract.py"):
        value = (root / "deploy/ops" / helper).read_bytes().replace(b"\r\n", b"\n")
        assert hashlib.sha256(value).hexdigest() in executor
    assert "PLACEHOLDER" not in executor
    for action in ("stage", "verify", "status"):
        assert f"smartscan-uat-ocr-stage {action}" in sudoers
    for forbidden in (" bash", " sh", "*", " rm", "curl", "wget", "docker", "prune"):
        assert forbidden not in sudoers.lower()
    assert "stage|verify|status" in executor
    assert "[[ $# -eq 1 ]]" in executor


def test_stage_executor_bash_syntax_and_argument_injection() -> None:
    bash = shutil.which("bash")
    if bash is None:
        pytest.skip("Bash语法和参数门禁由Ubuntu Runner补证")
    executor = Path(__file__).resolve().parents[1] / "deploy/ops/smartscan-uat-ocr-stage"
    syntax = subprocess.run(
        [bash, "-n", str(executor)], capture_output=True, text=True, check=False
    )
    assert syntax.returncode == 0, syntax.stderr
    extra = subprocess.run(
        [bash, str(executor), "status", ";id"], capture_output=True, text=True, check=False
    )
    unknown = subprocess.run(
        [bash, str(executor), "bash"], capture_output=True, text=True, check=False
    )
    assert extra.returncode != 0 and "invalid_arguments" in extra.stderr
    assert unknown.returncode != 0 and "invalid_command" in unknown.stderr


@pytest.mark.skipif(os.name == "nt", reason="visudo仅在Ubuntu Runner补证")
def test_stage_sudoers_syntax_on_linux() -> None:
    visudo = shutil.which("visudo")
    if visudo is None:
        pytest.skip("当前Linux环境没有visudo")
    sudoers = Path(__file__).resolve().parents[1] / "deploy/ops/smartscan-uat-ocr-stage.sudoers"
    result = subprocess.run(
        [visudo, "-cf", str(sudoers)], capture_output=True, text=True, check=False
    )
    assert result.returncode == 0, result.stderr
