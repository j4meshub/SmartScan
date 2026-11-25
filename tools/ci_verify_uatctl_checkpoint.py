#!/usr/bin/env python3
"""在隔离 Linux Docker daemon 中验证OPS-001M迁移与核心启动状态机。"""

from __future__ import annotations

import json
import os
import re
from pathlib import Path

from deploy.ops import smartscan_uat_config as config
from deploy.ops import smartscan_uat_ocr_stage as ocr_stage
from deploy.ops import smartscan_uat_validators as validators
from deploy.ops import smartscan_uatctl as uatctl

GIB = 1024**3
ROOT = Path(os.environ["GITHUB_WORKSPACE"])
ARCHIVES = ROOT / ".smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
CONFIG = Path("/etc/smartscan/uat")
DATA = Path("/mnt/data/smartscan/uat")
OCR_LAYER = ROOT / ".smartscan-offline-transfer/ocr/smartscan-ocr-layer-fdae8d61585e.tar.gz"


def report_core_failure(controller: uatctl.Controller) -> None:
    """CI失败时只输出固定服务的脱敏状态与异常摘要。"""

    secret_pattern = re.compile(
        r"(?i)(password|secret|token|api[_-]?key|postgresql(?:\+\w+)?://)\s*[:=]?\s*\S+"
    )
    error_pattern = re.compile(
        r"(?i)(error|exception|traceback|permission denied|read-only|no such file|failed)"
    )
    for service in ("api", "worker-cpu-1", "worker-cpu-2", "nginx"):
        container_id = controller._compose("ps", "-a", "-q", service).strip()
        if not container_id:
            print(json.dumps({"service": service, "status": "missing"}, sort_keys=True))
            continue
        state_raw = controller.runner.run(
            [
                "/usr/bin/docker",
                "inspect",
                "--format",
                "{{json .State}}",
                container_id,
            ]
        )
        state = json.loads(state_raw)
        evidence = {
            "service": service,
            "status": state.get("Status"),
            "exit_code": state.get("ExitCode"),
            "oom_killed": state.get("OOMKilled"),
            "runtime_error": bool(state.get("Error")),
            "health": (state.get("Health") or {}).get("Status"),
        }
        logs = controller.runner.run_result(
            ["/usr/bin/docker", "logs", "--tail", "60", container_id],
            timeout_seconds=10,
        )
        combined = f"{logs.stdout}\n{logs.stderr}"
        candidates = [line.strip() for line in combined.splitlines() if error_pattern.search(line)]
        if candidates:
            evidence["error_summary"] = secret_pattern.sub(r"\1=<redacted>", candidates[-1])[:500]
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def prepare_model(root: Path) -> None:
    assert OCR_LAYER.is_file(), "真实OCR Layer缺失"
    result = ocr_stage.stage_fixed(
        OCR_LAYER,
        root,
        enforce_upload_permissions=False,
        root_uid=0,
    )
    assert result["status"] == "passed"


def prepare_config(deploy_uid: int) -> tuple[config.Paths, validators.NativeValidators]:
    CONFIG.mkdir(parents=True, mode=0o700)
    for path, mode in (
        (DATA / "postgres", 0o700),
        (DATA / "data", 0o750),
        (DATA / "models", 0o755),
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
        active_nginx=CONFIG / "active-nginx-must-remain-absent.conf",
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
    before_migration_running = set(
        controller._compose("ps", "--status", "running", "--services").splitlines()
    )
    assert before_migration_running == {"postgres"}

    migration = controller.run_migrations()
    assert migration["status"] == "passed"
    after_migration = controller.status()
    assert after_migration["next_required"] == "core_started"
    assert "migrations_completed" in after_migration["completed"]
    assert not paths.migration_failure.exists()
    current = controller._compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "smartscan",
        "-d",
        "smartscan",
        "-Atqc",
        "SELECT version_num FROM alembic_version",
    )
    assert current == "20261022_0024"
    schema_evidence = controller._compose(
        "exec",
        "-T",
        "postgres",
        "psql",
        "-U",
        "smartscan",
        "-d",
        "smartscan",
        "-Atqc",
        "SELECT (SELECT count(*) FROM information_schema.tables "
        "WHERE table_schema='public') || ':' || "
        "(SELECT count(*) FROM pg_indexes WHERE schemaname='public' "
        "AND tablename='ai_media_grants') || ':' || "
        "(SELECT count(*) FROM pg_constraint WHERE conrelid='public.ai_media_grants'::regclass)",
    )
    table_count, index_count, constraint_count = (int(item) for item in schema_evidence.split(":"))
    assert table_count >= 30
    assert index_count == 9
    assert constraint_count >= 9
    after_migration_running = set(
        controller._compose("ps", "--status", "running", "--services").splitlines()
    )
    assert after_migration_running == {"postgres"}

    migrate_id = controller._compose("ps", "-a", "-q", "migrate")
    assert migrate_id
    migrate_runtime = json.loads(controller.runner.run(["/usr/bin/docker", "inspect", migrate_id]))[
        0
    ]
    assert migrate_runtime["HostConfig"]["ReadonlyRootfs"] is True
    tmpfs = migrate_runtime["HostConfig"]["Tmpfs"]
    assert set(tmpfs) == {"/tmp"}
    tmpfs_options = set(tmpfs["/tmp"].split(","))
    assert {"rw", "noexec", "nosuid", "nodev", "mode=1777", "uid=10001", "gid=10001"}.issubset(
        tmpfs_options
    )
    assert tmpfs_options.intersection({"size=32m", "size=33554432"})
    assert migrate_runtime["Mounts"] == []
    storage_values = [
        item
        for item in migrate_runtime["Config"]["Env"]
        if item.startswith("SMARTSCAN_STORAGE_ROOT=")
    ]
    assert storage_values == ["SMARTSCAN_STORAGE_ROOT=/tmp/smartscan-data"]
    assert migrate_runtime["State"]["ExitCode"] == 0

    repeated = controller.run_migrations()
    assert repeated["already_complete"] is True
    assert controller._compose("ps", "-a", "-q", "migrate") == migrate_id

    try:
        resumed = controller.resume_basic_uat()
    except uatctl.ControllerError:
        report_core_failure(controller)
        raise
    assert resumed == {
        "status": "passed",
        "next_required": "stage-nginx",
        "secrets_included": False,
    }
    final = controller.status()
    assert final["next_required"] == "nginx_staged"
    assert {"core_started", "core_verified"}.issubset(final["completed"])
    assert not paths.active_nginx.exists()
    running = set(controller._compose("ps", "--status", "running", "--services").splitlines())
    assert running == {"postgres", "api", "worker-cpu-1", "worker-cpu-2", "nginx"}
    worker_heartbeats = "0"
    for _ in range(30):
        worker_heartbeats = controller._compose(
            "exec",
            "-T",
            "postgres",
            "psql",
            "-U",
            "smartscan",
            "-d",
            "smartscan",
            "-Atqc",
            "SELECT count(*) FROM worker_heartbeats",
        )
        if int(worker_heartbeats) >= 2:
            break
        __import__("time").sleep(2)
    assert int(worker_heartbeats) >= 2
    print(
        json.dumps(
            {
                "checkpoint": "migration-and-core-complete",
                "database": "healthy",
                "images": 6,
                "migration_target": "20261022_0024",
                "next_required": "stage-nginx",
                "core_services": 5,
                "shared_nginx_touched": False,
                "registry_access": False,
                "status": "passed",
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
