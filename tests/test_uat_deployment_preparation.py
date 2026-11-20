from __future__ import annotations

import hashlib
import importlib.util
import json
import os
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).parents[1]
HELPER = ROOT / "deploy" / "ops" / "smartscan_uat_config.py"
EXECUTOR = ROOT / "deploy" / "ops" / "smartscan-uat-deployment-preparation"
SUDOERS = ROOT / "deploy" / "sudoers" / "smartscan-uat-deployment-preparation"
FIELD_SPEC = ROOT / "deploy" / "compose" / "uat-config-fields.json"
GUIDE = ROOT / "docs" / "OPS001C_UAT_DEPLOYMENT_PREPARATION.md"

SPEC = importlib.util.spec_from_file_location("smartscan_uat_config", HELPER)
assert SPEC is not None and SPEC.loader is not None
CONFIG = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = CONFIG
SPEC.loader.exec_module(CONFIG)


def _chmod_600(path: Path) -> None:
    path.chmod(0o600)


def _write_json(path: Path, value: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    _chmod_600(path)


def _paths(tmp_path: Path):
    config = tmp_path / "etc" / "smartscan" / "uat"
    mount = tmp_path / "mnt" / "data" / "smartscan" / "uat"
    config.mkdir(parents=True)
    (mount / "postgres").mkdir(parents=True)
    (mount / "data").mkdir()
    (mount / "models" / "ocr").mkdir(parents=True)
    return CONFIG.Paths(
        config_root=config,
        input_file=config / "deployment-input.json",
        deploy_env=config / "deploy.env",
        runtime_env=config / "runtime.env",
        allocation=config / "shared-host-allocation.json",
        preflight=config / "preflight-summary.json",
        loop_evidence=config / "loop-storage-evidence.json",
        bootstrap_password=config / "bootstrap-admin-password",
        image_identities=config / "image-identities.json",
        postgres_root=mount / "postgres",
        data_root=mount / "data",
        model_root=mount / "models" / "ocr",
    )


def _prepare_inputs(paths) -> None:
    _write_json(
        paths.input_file,
        {
            "schema_version": "1.0",
            "target_hostname": "ctiecaiserver",
            "shared_entry_origin": "http://192.0.2.10:8077",
            "confirmation": {
                "confirmed_by": "ci-shared-user",
                "confirmed_at": "2026-11-20T00:00:00Z",
                "change_record": "CI-CHANGE-001",
                "validation_record": "CI-VALIDATION-001",
                "rollback_record": "CI-ROLLBACK-001",
            },
            "networks": {
                "data": {"subnet": "192.0.2.0/28", "gateway": "192.0.2.1"},
                "edge": {"subnet": "192.0.2.16/28", "gateway": "192.0.2.17"},
                "egress": {"subnet": "192.0.2.32/28", "gateway": "192.0.2.33"},
            },
            "reserved_cidrs": ["10.0.0.0/9"],
            "monitoring_record": "CI-MONITORING-GAP-ACCEPTED",
        },
    )
    _write_json(
        paths.preflight,
        {
            "schema_version": "1.0",
            "status": "passed",
            "captured_at": "2026-11-20T00:00:00Z",
            "contains_sensitive_data": False,
        },
    )
    _write_json(
        paths.loop_evidence,
        {
            "schema_version": "1.0",
            "captured_at": "2026-11-20T00:00:00Z",
            "backing_file": {
                "size_bytes": 50 * 1024**3,
                "allocated_bytes": 50 * 1024**3,
                "sparse": False,
            },
            "filesystem": {
                "type": "ext4",
                "label": "smartscan-uat",
                "reserved_blocks_percent": 0,
                "usable_bytes": 49 * 1024**3,
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


def _prepare_model(paths) -> None:
    model_file = paths.model_root / "det" / "model.bin"
    model_file.parent.mkdir()
    model_file.write_bytes(b"fixed-test-model")
    manifest = {
        "schema_version": 1,
        "paddleocr_version": "3.7.0",
        "paddlepaddle_version": "3.3.1",
        "model_version": "PP-OCRv6-small-v1",
        "source": "CI固定测试资产",
        "license": "测试代码生成，无第三方数据",
        "text_detection_dir": "det",
        "text_recognition_dir": "det",
        "files": {"det/model.bin": hashlib.sha256(model_file.read_bytes()).hexdigest()},
    }
    (paths.model_root / "manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False), encoding="utf-8"
    )


def test_generator_creates_complete_redacted_config_with_fixed_images(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    _prepare_model(paths)
    uid = os.getuid() if hasattr(os, "getuid") else 0

    generated = CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)
    verified = CONFIG.verify(paths, deploy_uid=uid, root_uid=uid)

    assert generated["status"] == "passed"
    assert generated["secrets_included"] is False
    assert verified["status"] == "passed"
    assert verified["fixed_image_count"] == 6
    deploy = CONFIG._parse_env(paths.deploy_env)
    runtime = CONFIG._parse_env(paths.runtime_env)
    for key, reference in CONFIG.ACCEPTED_IMAGES.items():
        assert deploy[key] == reference
    assert runtime["SMARTSCAN_SMS_MODE"] == "disabled"
    assert runtime["SMARTSCAN_WECOM_MODE"] == "disabled"
    assert runtime["SMARTSCAN_AI_PROVIDERS"] == "[]"
    assert runtime["SMARTSCAN_AI_GATEWAY_URL"] == ""
    assert runtime["SMARTSCAN_AI_MOCK_MODE"] == "false"
    assert runtime["SMARTSCAN_STORAGE_MIN_FREE_BYTES"] == str(2 * 1024**3)
    for path in (
        paths.deploy_env,
        paths.runtime_env,
        paths.allocation,
        paths.bootstrap_password,
    ):
        if os.name != "nt":
            assert stat.S_IMODE(path.stat().st_mode) == 0o600
    serialized = json.dumps(generated, ensure_ascii=False)
    for key in CONFIG.SECRET_FIELDS:
        assert key in serialized
        secret_value = deploy.get(key, runtime.get(key, ""))
        assert secret_value not in serialized


def test_generation_is_idempotent_without_rotating_secrets(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    _prepare_model(paths)
    uid = os.getuid() if hasattr(os, "getuid") else 0

    first = CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)
    before = paths.runtime_env.read_bytes()
    second = CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)

    assert first["result"] == "generated"
    assert second["result"] == "already_ready"
    assert paths.runtime_env.read_bytes() == before


def test_field_classification_exactly_covers_generated_configuration(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)
    specification = json.loads(FIELD_SPEC.read_text(encoding="utf-8"))

    for section, generated in (
        ("deploy_env", CONFIG._parse_env(paths.deploy_env)),
        ("runtime_env", CONFIG._parse_env(paths.runtime_env)),
    ):
        groups = specification[section]
        classified = [key for values in groups.values() for key in values]
        assert len(classified) == len(set(classified))
        assert set(classified) == set(generated)


def test_generation_rejects_partial_state_after_interruption(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    paths.deploy_env.write_text("partial=true\n", encoding="utf-8")

    with pytest.raises(CONFIG.ConfigError, match="部分状态"):
        CONFIG.generate(paths, deploy_uid=0, root_uid=0)


def test_generation_rejects_symlink_and_wrong_evidence_permissions(tmp_path: Path) -> None:
    if os.name == "nt":
        pytest.skip("Windows开发模式不稳定支持普通用户符号链接")
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    real_input = paths.input_file.with_suffix(".real")
    paths.input_file.rename(real_input)
    paths.input_file.symlink_to(real_input)
    uid = os.getuid()

    with pytest.raises(CONFIG.ConfigError, match="固定文件无效"):
        CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)

    paths.input_file.unlink()
    real_input.rename(paths.input_file)
    paths.preflight.chmod(0o644)
    with pytest.raises(CONFIG.ConfigError, match="权限必须为0600"):
        CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)


def test_verify_rejects_missing_real_ocr_model(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    _prepare_inputs(paths)
    uid = os.getuid() if hasattr(os, "getuid") else 0
    CONFIG.generate(paths, deploy_uid=uid, root_uid=uid)

    with pytest.raises(CONFIG.ConfigError, match="OCR模型manifest缺失"):
        CONFIG.verify(paths, deploy_uid=uid, root_uid=uid)


def test_image_identity_evidence_binds_all_six_digests_and_uid_contract(tmp_path: Path) -> None:
    paths = _paths(tmp_path)
    identities = {}
    for key, reference in CONFIG.ACCEPTED_IMAGES.items():
        uid_gid = (70, 70) if key == "SMARTSCAN_UAT_POSTGRES_IMAGE" else (10001, 10001)
        identities[key] = {
            "reference": reference,
            "repo_digest_verified": True,
            "config_user": "verified-after-pull",
            "runtime_uid": uid_gid[0],
            "runtime_gid": uid_gid[1],
        }
    _write_json(
        paths.image_identities,
        {
            "schema_version": "1.0",
            "captured_at": "2026-11-20T00:00:00Z",
            "platform": "linux/amd64",
            "images": identities,
        },
    )
    uid = os.getuid() if hasattr(os, "getuid") else 0

    result = CONFIG.validate_image_identities(paths, root_uid=uid)
    assert result["SMARTSCAN_UAT_POSTGRES_IMAGE"] == (70, 70)
    assert result["SMARTSCAN_UAT_API_IMAGE"] == (10001, 10001)

    identities["SMARTSCAN_UAT_API_IMAGE"]["reference"] = (
        "ghcr.io/example/changed@sha256:" + "0" * 64
    )
    _write_json(
        paths.image_identities,
        {
            "schema_version": "1.0",
            "captured_at": "2026-11-20T00:00:00Z",
            "platform": "linux/amd64",
            "images": identities,
        },
    )
    with pytest.raises(CONFIG.ConfigError, match="引用不一致"):
        CONFIG.validate_image_identities(paths, root_uid=uid)


def test_executor_and_sudoers_allow_only_five_fixed_commands() -> None:
    executor = EXECUTOR.read_text(encoding="utf-8")
    sudoers = SUDOERS.read_text(encoding="utf-8")
    command = "/usr/local/libexec/smartscan/smartscan-uat-deployment-preparation"
    actions = (
        "prepare-directories",
        "generate-config",
        "verify-config",
        "apply-ownership",
        "status",
    )

    assert "set -euo pipefail" in executor
    assert "umask 077" in executor
    assert 'EXPECTED_HOSTNAME="ctiecaiserver"' in executor
    assert 'EXPECTED_SUDO_USER="szhzx"' in executor
    assert hashlib.sha256(HELPER.read_bytes()).hexdigest() in executor
    assert "docker " not in executor
    assert "nginx" not in executor.casefold()
    assert "prune" not in executor
    assert "rm " not in executor
    assert "unlink" not in executor
    assert sudoers.count(command) == 5
    for action in actions:
        assert f"{command} {action}" in sudoers
    assert "sudo bash" not in sudoers
    assert "sudo sh" not in sudoers
    assert "systemctl" not in sudoers
    assert "*" not in sudoers
    assert "?" not in sudoers


def test_manual_installation_guide_pins_all_root_asset_digests() -> None:
    guide = GUIDE.read_text(encoding="utf-8")
    for path in (EXECUTOR, HELPER, SUDOERS):
        assert hashlib.sha256(path.read_bytes()).hexdigest() in guide
    assert "本工作包没有连接或修改共享服务器" in guide
    assert "prepare-directories" in guide


def test_executor_rejects_extra_arguments_before_state_change() -> None:
    bash = shutil.which("bash")
    if bash is None or os.name == "nt":
        pytest.skip("动态Bash测试由GitHub Linux Runner执行")
    result = subprocess.run(
        [bash, str(EXECUTOR), "prepare-directories", ";id"],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 64
    assert "用法" in result.stderr


def test_executor_bash_syntax() -> None:
    bash = shutil.which("bash")
    if bash is None or os.name == "nt":
        pytest.skip("Bash语法测试由GitHub Linux Runner执行")
    result = subprocess.run(
        [bash, "-n", str(EXECUTOR)], text=True, capture_output=True, check=False
    )
    assert result.returncode == 0, result.stderr


def test_sudoers_visudo_syntax() -> None:
    visudo = shutil.which("visudo")
    if visudo is None or os.name == "nt":
        pytest.skip("sudoers语法测试由GitHub Linux Runner执行")
    result = subprocess.run(
        [visudo, "-cf", str(SUDOERS)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode == 0, result.stderr
