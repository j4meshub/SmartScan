from __future__ import annotations

import json
import os
import shlex
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from deploy.ops import smartscan_uat_config as config
from tools.run_uat_bootstrap_over_ssh import REMOTE_COMMAND, SSH_ALIAS, build_payload, run_prepare
from tools.shared_host_preflight import (
    GIB,
    PreflightError,
    _bootstrap_networks,
    _inspect_nginx_configuration,
    _prepare_output_root,
    _validate_ocr_outputs,
    _validate_shared_runtime_health,
    _write_bootstrap_documents,
    build_bootstrap_deployment_input,
    build_loop_evidence,
    build_uat_allocation,
)
from tools.validate_uat_loop_storage import validate_loop_storage_evidence


def _snapshot() -> dict[str, object]:
    return {
        "network": {
            "addresses": [{"address": "10.8.0.150"}],
            "routes": [{"family": 4, "dst": "10.8.0.0/24"}],
        },
        "docker": {
            "networks": [{"subnets": [{"subnet": "172.20.0.0/16"}]}],
        },
    }


def _spec() -> dict[str, object]:
    return {
        "schema_version": "1.0",
        "networks": {
            "data": "172.29.240.0/28",
            "edge": "172.29.240.16/28",
            "egress": "172.29.240.32/28",
        },
    }


def test_bootstrap_input_matches_existing_config_contract() -> None:
    deployment = build_bootstrap_deployment_input(
        _snapshot(),
        _spec(),
        ssh_connection="198.51.100.20 50000 10.8.0.150 22",
        captured_at="2026-11-23T03:00:00Z",
    )

    validated = config._validate_input(deployment)
    allocation = build_uat_allocation(deployment)

    assert config._allocation(validated) == allocation
    assert deployment["networks"]["data"]["gateway"] == "172.29.240.1"
    assert deployment["shared_entry_origin"] == "http://10.8.0.150:8077"
    assert set(deployment["reserved_cidrs"]) == {"10.8.0.0/24", "172.20.0.0/16"}
    assert "password" not in json.dumps(deployment, ensure_ascii=False).casefold()
    assert "token" not in json.dumps(deployment, ensure_ascii=False).casefold()


def test_bootstrap_input_rejects_extra_fields_and_overlapping_networks() -> None:
    spec = _spec()
    spec["secret"] = "must-not-be-accepted"
    with pytest.raises(PreflightError, match="只允许"):
        _bootstrap_networks(spec)

    spec = _spec()
    spec["networks"]["edge"] = "172.29.240.0/28"
    with pytest.raises(PreflightError, match="重叠"):
        _bootstrap_networks(spec)


def test_loop_evidence_matches_existing_validator(tmp_path: Path) -> None:
    deployment = build_bootstrap_deployment_input(
        _snapshot(),
        _spec(),
        ssh_connection="198.51.100.20 50000 10.8.0.150 22",
        captured_at="2026-11-23T03:00:00Z",
    )
    allocation = build_uat_allocation(deployment)
    verify_output = "\n".join(
        (
            "status=passed",
            "action=verify",
            f"backing_size_bytes={50 * GIB}",
            "fully_preallocated=true",
            "filesystem=ext4",
            "label=smartscan-uat",
            f"usable_bytes={49 * GIB}",
            "mount_active=true",
            "mount_source=loop-redacted",
            "autoclear=true",
            "unit_enabled=true",
            "unit_active=true",
        )
    )
    findmnt_output = json.dumps(
        {
            "filesystems": [
                {
                    "source": "/dev/loop7",
                    "target": "/mnt/data/smartscan/uat",
                    "fstype": "ext4",
                    "options": "rw,nodev,nosuid,noatime",
                }
            ]
        }
    )
    evidence = build_loop_evidence(
        verify_output,
        findmnt_output,
        captured_at="2026-11-23T03:00:00Z",
    )
    allocation_path = tmp_path / "allocation.json"
    evidence_path = tmp_path / "loop-storage-evidence.json"
    allocation_path.write_text(json.dumps(allocation), encoding="utf-8")
    evidence_path.write_text(json.dumps(evidence), encoding="utf-8")
    mount_unit = (
        Path(__file__).parents[1] / "deploy" / "systemd" / "mnt-data-smartscan-uat.mount.template"
    )

    result = validate_loop_storage_evidence(
        allocation_path,
        mount_unit,
        evidence_path,
        ci_fixture=True,
    )

    assert result.mode == "created"
    assert result.usable_bytes == 49 * GIB
    assert evidence["mount"]["source"] == "/dev/loop7"


def test_loop_evidence_rejects_non_loop_source() -> None:
    verify_output = "\n".join(
        (
            "status=passed",
            "action=verify",
            f"backing_size_bytes={50 * GIB}",
            "fully_preallocated=true",
            "filesystem=ext4",
            "label=smartscan-uat",
            f"usable_bytes={49 * GIB}",
            "mount_active=true",
            "autoclear=true",
            "unit_enabled=true",
            "unit_active=true",
        )
    )
    findmnt_output = json.dumps(
        {
            "filesystems": [
                {
                    "source": "/dev/sda1",
                    "target": "/mnt/data/smartscan/uat",
                    "fstype": "ext4",
                    "options": "rw,nodev,nosuid,noatime",
                }
            ]
        }
    )

    with pytest.raises(PreflightError, match="不是loop"):
        build_loop_evidence(
            verify_output,
            findmnt_output,
            captured_at="2026-11-23T03:00:00Z",
        )


def test_nginx_structure_accepts_8077_and_rejects_smartscan_conflict(tmp_path: Path) -> None:
    conf_dir = tmp_path / "conf.d"
    conf_dir.mkdir()
    main = tmp_path / "nginx.conf"
    main.write_text(f"include {conf_dir}/*.conf;\n", encoding="utf-8")
    site = conf_dir / "shared.conf"
    site.write_text("server {\n  listen 8077;\n  location /existing/ { return 204; }\n}\n")

    _inspect_nginx_configuration(main)

    site.write_text("server {\n  listen 8077;\n  location /smartscan/ { return 204; }\n}\n")
    with pytest.raises(PreflightError, match="SmartScan路径"):
        _inspect_nginx_configuration(main)


def test_ocr_gate_requires_installed_fixed_version() -> None:
    valid = json.dumps(
        {"artifact_version": "PP-OCRv6-small-v1", "bytes": 31_495_253, "status": "passed"}
    )
    status = json.dumps(
        {
            "artifact_version": "PP-OCRv6-small-v1",
            "bytes": 31_495_253,
            "installed": True,
            "status": "passed",
        }
    )
    _validate_ocr_outputs(valid, status)

    with pytest.raises(PreflightError, match="未安装"):
        _validate_ocr_outputs(valid, status.replace("true", "false"))


def test_shared_runtime_health_requires_8077_and_healthy_containers() -> None:
    snapshot = {
        "network": {"listeners": [{"protocol": "tcp", "address": "0.0.0.0", "port": 8077}]},
        "docker": {"containers": [{"state": "running", "status": "Up 2 days (healthy)"}]},
    }
    _validate_shared_runtime_health(snapshot)

    snapshot["docker"]["containers"][0]["status"] = "Up 1 minute (unhealthy)"
    with pytest.raises(PreflightError, match="不健康"):
        _validate_shared_runtime_health(snapshot)


def test_ssh_launcher_keeps_private_spec_out_of_command_line() -> None:
    spec_raw = json.dumps(_spec()).encode()
    calls: list[tuple[list[str], bytes]] = []

    def runner(args, **kwargs):
        calls.append((args, kwargs["input"]))
        return subprocess.CompletedProcess(args=args, returncode=0)

    assert run_prepare(spec_raw, runner=runner) == 0
    assert len(calls) == 1
    args, payload = calls[0]
    assert args == ["ssh", SSH_ALIAS, REMOTE_COMMAND]
    assert spec_raw not in " ".join(args).encode()
    source_size_raw, framed = payload.split(b"\n", 1)
    source_size = int(source_size_raw)
    assert framed[source_size:] == spec_raw
    assert b"prepare-bootstrap" in framed[:source_size]


def test_payload_rejects_unknown_input_fields() -> None:
    spec = _spec()
    spec["shared_entry_origin"] = "must-not-be-supplied"

    with pytest.raises(PreflightError, match="只允许"):
        build_payload(json.dumps(spec).encode())


def test_remote_loader_preserves_framed_standard_input() -> None:
    loader = shlex.split(REMOTE_COMMAND)
    assert loader[:2] == ["python3", "-c"]
    assert "__generator_sha256__" in loader[2]
    source = b"import sys; print(sys.stdin.read(), end='')"
    private_input = b'{"private":"value"}'
    payload = str(len(source)).encode() + b"\n" + source + private_input

    completed = subprocess.run(
        [sys.executable, "-c", loader[2]],
        input=payload,
        capture_output=True,
        check=False,
    )

    assert completed.returncode == 0
    assert completed.stdout == private_input


@pytest.mark.skipif(os.name == "nt", reason="POSIX所有权和权限由Ubuntu Runner验证")
def test_bootstrap_output_is_atomic_private_and_non_overwriting(tmp_path: Path) -> None:
    root = tmp_path / "bootstrap"
    uid = os.getuid()
    _prepare_output_root(root, expected_uid=uid)
    documents = {
        "deployment-input.json": {"kind": "deployment"},
        "preflight-summary.json": {"kind": "preflight"},
        "loop-storage-evidence.json": {"kind": "loop"},
    }

    _write_bootstrap_documents(root, documents)

    assert stat.S_IMODE(root.stat().st_mode) == 0o700
    for name in documents:
        info = (root / name).lstat()
        assert stat.S_ISREG(info.st_mode)
        assert info.st_uid == uid
        assert info.st_nlink == 1
        assert stat.S_IMODE(info.st_mode) == 0o600
    with pytest.raises(PreflightError, match="必须为空"):
        _prepare_output_root(root, expected_uid=uid)
