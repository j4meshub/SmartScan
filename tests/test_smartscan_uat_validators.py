from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
from types import SimpleNamespace

import pytest

from deploy.ops import smartscan_uat_config as config
from deploy.ops import smartscan_uat_validators as validators

TEST_UID = os.getuid() if hasattr(os, "getuid") else 0


class FixedRunner:
    def __init__(self, outputs: dict[tuple[str, ...], str]) -> None:
        self.outputs = outputs
        self.calls: list[list[str]] = []

    def run(
        self,
        arguments: list[str],
        *,
        check: bool = True,
        timeout_seconds: int | None = None,
        environment: dict[str, str] | None = None,
    ) -> str:
        del check, timeout_seconds, environment
        self.calls.append(arguments)
        return self.outputs.get(tuple(arguments), "")


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def _model(root: Path) -> None:
    payloads: dict[str, bytes] = {}
    for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"):
        (root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("inference.json", "inference.pdiparams", "inference.yml"):
            relative = f"{directory}/{name}"
            payloads[relative] = f"fixed:{relative}".encode()
    for relative in validators.EXPECTED_EVIDENCE_FILES:
        payloads[relative] = f"evidence:{relative}".encode()
    metadata = {
        relative: {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
        for relative, value in payloads.items()
        if relative in validators.EXPECTED_MODEL_FILES
    }
    evidence = {
        relative: {"sha256": hashlib.sha256(value).hexdigest(), "size": len(value)}
        for relative, value in payloads.items()
        if relative in validators.EXPECTED_EVIDENCE_FILES
    }
    for relative, value in payloads.items():
        target = root / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        if target.exists():
            target.chmod(0o644)
        target.write_bytes(value)
        target.chmod(0o444)
    manifest = {
        "schema_version": 1,
        "artifact_kind": "smartscan-offline-ocr-models",
        "artifact_version": validators.EXPECTED_MODEL_VERSION,
        "backend": "paddle_static",
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": validators.EXPECTED_MODEL_VERSION,
        "license": "Apache-2.0",
        "text_detection_dir": "PP-OCRv6_small_det",
        "text_recognition_dir": "PP-OCRv6_small_rec",
        "conversion": {"performed": False, "description": "仅规范化目录名，模型字节未修改"},
        "source": "PaddlePaddle/PaddleOCR固定来源",
        "source_commit": "9be7b7c366f568d82a19341e072a3144ddd025a2",
        "files": {relative: item["sha256"] for relative, item in metadata.items()},
        "file_metadata": metadata,
        "evidence_files": evidence,
        "total_model_bytes": sum(item["size"] for item in metadata.values()),
    }
    manifest_path = root / "manifest.json"
    if manifest_path.exists():
        manifest_path.chmod(0o644)
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")
    manifest_path.chmod(0o444)
    for directory in (root, root / "PP-OCRv6_small_det", root / "PP-OCRv6_small_rec"):
        directory.chmod(0o755)


def _config_paths(tmp_path: Path) -> tuple[config.Paths, validators.Paths]:
    config_root = tmp_path / "etc" / "smartscan" / "uat"
    mount = tmp_path / "mnt" / "data" / "smartscan" / "uat"
    model = mount / "models" / "ocr"
    config_root.mkdir(parents=True)
    (mount / "postgres").mkdir(parents=True)
    (mount / "data").mkdir()
    model.mkdir(parents=True)
    _model(model)
    paths = config.Paths(
        config_root=config_root,
        input_file=config_root / "deployment-input.json",
        deploy_env=config_root / "deploy.env",
        runtime_env=config_root / "runtime.env",
        allocation=config_root / "shared-host-allocation.json",
        preflight=config_root / "preflight-summary.json",
        loop_evidence=config_root / "loop-storage-evidence.json",
        bootstrap_password=config_root / "bootstrap-admin-password",
        image_identities=config_root / "image-identities.json",
        postgres_root=mount / "postgres",
        data_root=mount / "data",
        model_root=model,
    )
    networks = {
        "data": {"subnet": "192.0.2.0/28", "gateway": "192.0.2.1"},
        "edge": {"subnet": "192.0.2.16/28", "gateway": "192.0.2.17"},
        "egress": {"subnet": "192.0.2.32/28", "gateway": "192.0.2.33"},
    }
    _write_json(
        paths.input_file,
        {
            "schema_version": "1.0",
            "target_hostname": "ctiecaiserver",
            "shared_entry_origin": "http://192.0.2.100:8077",
            "confirmation": {
                "confirmed_by": "shared-user",
                "confirmed_at": "2026-11-25T00:00:00Z",
                "change_record": "OPS-001K-CI",
                "validation_record": "OPS-001K-CI",
                "rollback_record": "OPS-001K-CI",
            },
            "networks": networks,
            "reserved_cidrs": ["10.0.0.0/8"],
            "monitoring_record": "人工检查能力缺口已接受",
        },
    )
    _write_json(
        paths.preflight,
        {
            "schema_version": "1.0",
            "status": "passed",
            "captured_at": "2026-11-25T00:00:00Z",
            "contains_sensitive_data": False,
        },
    )
    _write_json(
        paths.loop_evidence,
        {
            "schema_version": "1.0",
            "captured_at": "2026-11-25T00:00:00Z",
            "backing_file": {
                "size_bytes": 50 * validators.GIB,
                "allocated_bytes": 50 * validators.GIB,
                "sparse": False,
            },
            "filesystem": {
                "type": "ext4",
                "label": "smartscan-uat",
                "reserved_blocks_percent": 0,
                "usable_bytes": 49 * validators.GIB,
            },
            "mount": {
                "active": True,
                "target": "/mnt/data/smartscan/uat",
                "options": ["loop", "nodev", "nosuid", "noatime"],
            },
            "loop": {"autoclear": True},
            "systemd_unit": {"enabled": True, "active": True},
            "contains_sensitive_data": False,
        },
    )
    config.generate(paths, deploy_uid=TEST_UID, root_uid=TEST_UID)
    native = validators.Paths(
        config_root=config_root,
        mount_point=mount,
        model_root=model,
        deployment_input=paths.input_file,
        preflight_summary=paths.preflight,
        loop_evidence=paths.loop_evidence,
        deploy_env=paths.deploy_env,
        runtime_env=paths.runtime_env,
        allocation=paths.allocation,
        bootstrap_password=paths.bootstrap_password,
    )
    return paths, native


def test_model_and_config_native_validation_are_structured_and_secret_safe(tmp_path: Path) -> None:
    _, paths = _config_paths(tmp_path)
    validator = validators.NativeValidators(
        FixedRunner({}), paths, root_uid=TEST_UID, deploy_uid=TEST_UID
    )

    model = validator.verify_models()
    result = validator.verify_config()

    assert model.next_state == "models_verified" and model.passed
    assert model.evidence_summary["model_file_count"] == 6
    assert result.next_state == "config_verified" and result.passed
    assert result.evidence_summary["secret_values_printed"] is False
    serialized = json.dumps(result.evidence_summary, ensure_ascii=False)
    runtime_text = paths.runtime_env.read_text(encoding="utf-8")
    for line in runtime_text.splitlines():
        if any(name in line for name in config.SECRET_FIELDS):
            _, value = line.split("=", 1)
            assert not value or value not in serialized


@pytest.mark.parametrize(
    "payload,reason",
    [
        (b'{"a":1,"a":2}', "json_duplicate_key"),
        (b'{"a":1} trailing', "invalid_json"),
        (b"\xff", "non_utf8"),
        (b"[]", "root_not_object"),
    ],
)
def test_strict_json_rejects_ambiguous_or_invalid_documents(payload: bytes, reason: str) -> None:
    with pytest.raises(validators.ValidationError, match=reason):
        validators._strict_json_bytes(payload, "fixture")


def test_strict_json_accepts_legal_whitespace_and_field_order() -> None:
    assert validators._strict_json_bytes(b'{\n  "b": 2, "a": 1\n}', "fixture") == {
        "a": 1,
        "b": 2,
    }


def test_model_tamper_extra_file_and_hardlink_fail_closed(tmp_path: Path) -> None:
    _, paths = _config_paths(tmp_path)
    validator = validators.NativeValidators(
        FixedRunner({}), paths, root_uid=TEST_UID, deploy_uid=TEST_UID
    )
    target = paths.model_root / "PP-OCRv6_small_det" / "inference.json"
    target.chmod(0o644)
    target.write_bytes(b"tampered")
    target.chmod(0o444)
    with pytest.raises(validators.ValidationError, match="model_file_(size|digest)_mismatch"):
        validator.verify_models()

    _model(paths.model_root)
    extra = paths.model_root / "unexpected.bin"
    extra.write_bytes(b"extra")
    extra.chmod(0o444)
    with pytest.raises(validators.ValidationError, match="model_extra_or_missing_file"):
        validator.verify_models()


def test_config_duplicate_key_and_secret_mode_fail_closed(tmp_path: Path) -> None:
    _, paths = _config_paths(tmp_path)
    validator = validators.NativeValidators(
        FixedRunner({}), paths, root_uid=TEST_UID, deploy_uid=TEST_UID
    )
    paths.deployment_input.write_text('{"schema_version":"1.0","schema_version":"1.0"}')
    with pytest.raises(validators.ValidationError, match="json_duplicate_key"):
        validator.verify_config()


def test_storage_native_validation_uses_only_fixed_read_only_commands(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_mount = tmp_path / "mnt" / "data"
    backing = data_mount / "smartscan-loop" / "uat.ext4"
    mount = data_mount / "smartscan" / "uat"
    unit = tmp_path / "etc" / "systemd" / "system" / "mnt-data-smartscan-uat.mount"
    for path in (backing.parent, mount, unit.parent):
        path.mkdir(parents=True, exist_ok=True)
    backing.parent.chmod(0o700)
    mount.parent.chmod(0o755)
    mount.chmod(0o755)
    backing.write_bytes(b"fixture")
    backing.chmod(0o600)
    unit_text = (
        "RequiresMountsFor=/mnt/data\n"
        "What=/mnt/data/smartscan-loop/uat.ext4\n"
        "Where=/mnt/data/smartscan/uat\n"
        "Options=loop,nodev,nosuid,noatime"
    )
    unit.write_text(unit_text, encoding="utf-8")
    unit.chmod(0o644)
    spec = validators.StorageSpec(
        backing_bytes=1024,
        minimum_usable_bytes=900,
        minimum_host_reserve_bytes=100,
        minimum_host_reserve_percent=1,
        unit_sha256=hashlib.sha256(unit.read_bytes()).hexdigest(),
    )
    original = validators._regular_file

    def regular(path: Path, reason: str, **kwargs):
        result = original(path, reason, **kwargs)
        if path == backing:
            return SimpleNamespace(st_size=1024, st_blocks=2)
        return result

    monkeypatch.setattr(validators, "_regular_file", regular)
    outputs = {
        ("/usr/bin/findmnt", "-rn", "--target", str(data_mount), "-o", "TARGET"): str(data_mount),
        (
            "/usr/bin/findmnt",
            "-rn",
            "--mountpoint",
            str(mount),
            "-o",
            "SOURCE,FSTYPE,OPTIONS",
        ): "/dev/loop7 ext4 rw,nodev,nosuid,noatime",
        (
            "/usr/sbin/losetup",
            "-j",
            str(backing),
            "--noheadings",
            "--output",
            "NAME,AUTOCLEAR",
        ): "/dev/loop7 1",
        ("/usr/sbin/blkid", "-p", "-o", "export", str(backing)): "TYPE=ext4\nLABEL=smartscan-uat",
        ("/usr/sbin/dumpe2fs", "-h", str(backing)): "Reserved block count: 0",
        ("/usr/bin/df", "-B1", "--output=avail", str(mount)): "Avail\n900",
        ("/usr/bin/df", "-B1", "--output=size,avail", str(data_mount)): "Size Avail\n10000 1000",
    }
    runner = FixedRunner(outputs)
    paths = validators.Paths(
        data_mount=data_mount,
        backing_file=backing,
        mount_point=mount,
        unit_path=unit,
    )
    result = validators.NativeValidators(
        runner,
        paths,
        root_uid=TEST_UID,
        deploy_uid=TEST_UID,
        storage_spec=spec,
    ).verify_storage()
    assert result.next_state == "storage_verified"
    assert all(
        command[0]
        in {
            "/usr/bin/findmnt",
            "/usr/sbin/losetup",
            "/usr/sbin/blkid",
            "/usr/sbin/dumpe2fs",
            "/usr/bin/df",
            "/usr/bin/systemctl",
        }
        for command in runner.calls
    )
