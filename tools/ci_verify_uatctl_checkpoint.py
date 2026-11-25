#!/usr/bin/env python3
"""在隔离 Linux Docker daemon 中验证 OPS-001K 当前断点至迁移前门禁。"""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

from deploy.ops import smartscan_uat_config as config
from deploy.ops import smartscan_uat_validators as validators
from deploy.ops import smartscan_uatctl as uatctl

GIB = 1024**3
ROOT = Path(os.environ["GITHUB_WORKSPACE"])
ARCHIVES = ROOT / ".smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
CONFIG = Path("/etc/smartscan/uat")
DATA = Path("/mnt/data/smartscan/uat")


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def prepare_model(root: Path) -> None:
    payloads: dict[str, bytes] = {}
    for directory in ("PP-OCRv6_small_det", "PP-OCRv6_small_rec"):
        (root / directory).mkdir(parents=True, exist_ok=True)
        for name in ("inference.json", "inference.pdiparams", "inference.yml"):
            relative = f"{directory}/{name}"
            payloads[relative] = f"ops-001k-ci:{relative}".encode()
    for relative in validators.EXPECTED_EVIDENCE_FILES:
        payloads[relative] = f"ops-001k-ci-evidence:{relative}".encode()
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
        "source": "OPS-001K CI固定模型契约",
        "source_commit": "9be7b7c366f568d82a19341e072a3144ddd025a2",
        "files": {name: item["sha256"] for name, item in metadata.items()},
        "file_metadata": metadata,
        "evidence_files": evidence,
        "total_model_bytes": sum(item["size"] for item in metadata.values()),
    }
    (root / "manifest.json").write_text(json.dumps(manifest, ensure_ascii=False), encoding="utf-8")
    (root / "manifest.json").chmod(0o444)
    for directory in (root, root / "PP-OCRv6_small_det", root / "PP-OCRv6_small_rec"):
        directory.chmod(0o755)


def prepare_config(deploy_uid: int) -> tuple[config.Paths, validators.NativeValidators]:
    CONFIG.mkdir(parents=True, mode=0o700)
    for path, mode in (
        (DATA / "postgres", 0o700),
        (DATA / "data", 0o750),
        (DATA / "models" / "ocr", 0o755),
    ):
        path.mkdir(parents=True, exist_ok=True)
        path.chmod(mode)
    prepare_model(DATA / "models" / "ocr")
    paths = config.Paths(
        config_root=CONFIG,
        input_file=CONFIG / "deployment-input.json",
        deploy_env=CONFIG / "deploy.env",
        runtime_env=CONFIG / "runtime.env",
        allocation=CONFIG / "shared-host-allocation.json",
        preflight=CONFIG / "preflight-summary.json",
        loop_evidence=CONFIG / "loop-storage-evidence.json",
        bootstrap_password=CONFIG / "bootstrap-admin-password",
        image_identities=CONFIG / "image-identities.json",
        postgres_root=DATA / "postgres",
        data_root=DATA / "data",
        model_root=DATA / "models" / "ocr",
    )
    networks = {
        "data": {"subnet": "172.30.10.0/24", "gateway": "172.30.10.1"},
        "edge": {"subnet": "172.30.11.0/24", "gateway": "172.30.11.1"},
        "egress": {"subnet": "172.30.12.0/24", "gateway": "172.30.12.1"},
    }
    write_json(
        paths.input_file,
        {
            "schema_version": "1.0",
            "target_hostname": "ctiecaiserver",
            "shared_entry_origin": "http://192.0.2.100:8077",
            "confirmation": {
                "confirmed_by": "github-actions",
                "confirmed_at": "2026-11-25T00:00:00Z",
                "change_record": "OPS-001K-CI",
                "validation_record": "OPS-001K-CI",
                "rollback_record": "OPS-001K-CI",
            },
            "networks": networks,
            "reserved_cidrs": ["10.0.0.0/8"],
            "monitoring_record": "CI接受人工监控能力缺口",
        },
    )
    write_json(
        paths.preflight,
        {
            "schema_version": "1.0",
            "status": "passed",
            "captured_at": "2026-11-25T00:00:00Z",
            "contains_sensitive_data": False,
        },
    )
    write_json(
        paths.loop_evidence,
        {
            "schema_version": "1.0",
            "captured_at": "2026-11-25T00:00:00Z",
            "backing_file": {
                "size_bytes": 50 * GIB,
                "allocated_bytes": 50 * GIB,
                "sparse": False,
            },
            "filesystem": {
                "type": "ext4",
                "label": "smartscan-uat",
                "reserved_blocks_percent": 0,
                "usable_bytes": 49 * GIB,
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
    config.generate(paths, deploy_uid=deploy_uid, root_uid=0)
    native = validators.NativeValidators(
        uatctl.SubprocessRunner(),
        validators.Paths(
            config_root=CONFIG,
            mount_point=DATA,
            model_root=paths.model_root,
            deployment_input=paths.input_file,
            preflight_summary=paths.preflight,
            loop_evidence=paths.loop_evidence,
            deploy_env=paths.deploy_env,
            runtime_env=paths.runtime_env,
            allocation=paths.allocation,
            bootstrap_password=paths.bootstrap_password,
        ),
        root_uid=0,
        deploy_uid=deploy_uid,
    )
    return paths, native


def main() -> None:
    archive_root = ARCHIVES.stat()
    assert archive_root.st_uid != 0, "CI发布归档应模拟普通部署用户上传"
    deploy_uid = archive_root.st_uid
    ARCHIVES.chmod(0o700)
    for path in ARCHIVES.iterdir():
        if path.is_file():
            assert path.stat().st_uid == deploy_uid, f"归档所有者不一致：{path.name}"
            path.chmod(0o600)
    _, native = prepare_config(deploy_uid)
    paths = uatctl.Paths(
        config_root=CONFIG,
        data_root=DATA,
        upload_root=ARCHIVES,
        installed_release=CONFIG / "release-manifest.json",
        installed_map=CONFIG / "release-map.json",
        local_images_env=CONFIG / "local-images.env",
        image_identities=CONFIG / "image-identities.json",
        state_file=CONFIG / "uatctl-state.json",
        deploy_env=CONFIG / "deploy.env",
        runtime_env=CONFIG / "runtime.env",
        activation_plan=CONFIG / "nginx-activation.json",
        staged_nginx=CONFIG / "nginx-smartscan-8077.locations.conf",
        compose_file=ROOT / "deploy/compose/docker-compose.uat.yml",
        nginx_template=ROOT / "deploy/nginx/shared-8077-smartscan-location.conf.template",
        validator_module=ROOT / "deploy/ops/smartscan_uat_validators.py",
    )
    controller = uatctl.Controller(
        paths,
        root_uid=0,
        deploy_uid=deploy_uid,
        validator=native,
    )
    controller._record("preflight", {"ci_upgrade_checkpoint": True})
    controller._record("storage_verified", {"ci_upgrade_checkpoint": True})
    before = controller.status()
    assert before["completed"] == ["preflight", "storage_verified"]
    assert before["next_required"] == "models_verified"
    result = controller.resume_basic_uat()
    assert result == {
        "status": "waiting_confirmation",
        "next_required": "run-migrations",
        "secrets_included": False,
    }
    status = controller.status()
    assert status["next_required"] == "migrations_completed"
    assert "database_verified" in status["completed"]
    assert "migrations_completed" not in status["completed"]
    assert paths.image_identities.is_file()
    print(
        json.dumps(
            {
                "checkpoint": "preflight+storage_verified",
                "database": "healthy",
                "images": 6,
                "next_required": "run-migrations",
                "registry_access": False,
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
