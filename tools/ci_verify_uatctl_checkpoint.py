#!/usr/bin/env python3
"""在隔离Linux Docker daemon中验证OPS-001N单Worker增量发布状态机。"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import stat
import time
import urllib.request
from pathlib import Path

from deploy.ops import smartscan_uat_config as config
from deploy.ops import smartscan_uat_ocr_stage as ocr_stage
from deploy.ops import smartscan_uat_validators as validators
from deploy.ops import smartscan_uatctl as uatctl

GIB = 1024**3
ROOT = Path(os.environ["GITHUB_WORKSPACE"])
CANDIDATE_ARCHIVES = ROOT / ".smartscan-offline-transfer/images/smartscan-uat-2026-11-26-worker-fix"
BASE_ARCHIVES = ROOT / ".smartscan-offline-transfer/images/smartscan-uat-2026-11-24"
CI_VARIANT = "containerd29" if os.environ.get("SMARTSCAN_DOCKER29_CONTAINERD") == "1" else "legacy"
ARCHIVES = Path(os.environ["RUNNER_TEMP"]) / f"smartscan-uat-incremental-upload-{CI_VARIANT}"
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
            ["/usr/bin/docker", "logs", "--tail", "300", container_id],
            timeout_seconds=10,
        )
        combined = f"{logs.stdout}\n{logs.stderr}"
        candidates = [line.strip() for line in combined.splitlines() if error_pattern.search(line)]
        if candidates:
            sanitized: list[str] = []
            for line in candidates:
                value = secret_pattern.sub(r"\1=<redacted>", line)[:500]
                if value not in sanitized:
                    sanitized.append(value)
            evidence["error_summaries"] = sanitized[-8:]
        print(json.dumps(evidence, ensure_ascii=False, sort_keys=True))


def write_json(path: Path, value: object) -> None:
    path.write_text(json.dumps(value, ensure_ascii=False), encoding="utf-8")
    path.chmod(0o600)


def prepare_incremental_upload(deploy_uid: int) -> None:
    """构造与服务器一致的旧发布平铺目录和新候选子目录。"""

    assert not ARCHIVES.exists()
    ARCHIVES.mkdir(mode=0o700)
    os.chown(ARCHIVES, deploy_uid, deploy_uid)
    base = json.loads((BASE_ARCHIVES / "release-manifest.json").read_text(encoding="utf-8"))
    candidate = json.loads(
        (CANDIDATE_ARCHIVES / "release-manifest.json").read_text(encoding="utf-8")
    )
    for name in ("release-manifest.json", "release-map.json"):
        shutil.copyfile(BASE_ARCHIVES / name, ARCHIVES / name)
    candidate_root = ARCHIVES / candidate["release_id"]
    candidate_root.mkdir(mode=0o700)
    os.chown(candidate_root, deploy_uid, deploy_uid)
    for name in ("release-manifest.json", "release-map.json"):
        shutil.copyfile(CANDIDATE_ARCHIVES / name, candidate_root / name)
    base_images = {item["service"]: item for item in base["images"]}
    candidate_images = {item["service"]: item for item in candidate["images"]}
    changed_service = candidate["changed_services"][0]
    for service, item in base_images.items():
        source_root = BASE_ARCHIVES if service == changed_service else CANDIDATE_ARCHIVES
        shutil.copyfile(source_root / item["archive_name"], ARCHIVES / item["archive_name"])
    changed_image = candidate_images[changed_service]
    shutil.copyfile(
        CANDIDATE_ARCHIVES / changed_image["archive_name"],
        candidate_root / changed_image["archive_name"],
    )
    shutil.copyfile(
        CANDIDATE_ARCHIVES / "release-manifest.json", ARCHIVES / "candidate-release.json"
    )
    if changed_service == "web":
        write_json(
            candidate_root / "publish-network.json",
            {
                "schema_version": "1.0",
                "network_name": "smartscan-uat-publish",
                "subnet": "172.30.13.0/28",
                "gateway": "172.30.13.1",
                "risk_acknowledgement": "loopback-proxy-has-theoretical-egress",
                "confirmation": {
                    "confirmed_by": "ci",
                    "confirmed_at": "2026-11-27T00:00:00+08:00",
                    "change_record": "ci-fixed-network",
                    "validation_record": "ci-no-overlap",
                    "rollback_record": "remove-empty-network",
                },
            },
        )
    for path in ARCHIVES.rglob("*"):
        if path.is_file():
            os.chown(path, deploy_uid, deploy_uid)
            path.chmod(0o600)


def prepare_uploaded_candidate(deploy_uid: int) -> Path:
    """模拟固定普通用户上传入口；包装器不再绑定单次候选摘要。"""

    candidate = ARCHIVES / "candidate-release.json"
    os.chown(candidate, deploy_uid, deploy_uid)
    candidate.chmod(0o600)
    info = candidate.stat()
    assert info.st_uid == deploy_uid and stat.S_IMODE(info.st_mode) == 0o600 and info.st_nlink == 1
    return candidate


def verify_real_worker_task(password_path: Path, sample: Path, *, origin: str) -> None:
    """通过内部HTTP闭环提交真实图片，并确认由CPU Worker生成非空OCR。"""

    base = f"{origin}/api"
    device_headers = {
        "X-Device-ID": "ci:ops-001n",
        "X-Device-Name": "OPS-001N-CI",
        "X-Device-Platform": "ci",
    }

    def request_json(
        method: str,
        path: str,
        *,
        payload: object | None = None,
        raw: bytes | None = None,
        token: str | None = None,
        extra: dict[str, str] | None = None,
    ) -> tuple[int, object]:
        headers = dict(device_headers)
        if token:
            headers["Authorization"] = f"Bearer {token}"
        if payload is not None:
            raw = json.dumps(payload, separators=(",", ":")).encode()
            headers["Content-Type"] = "application/json"
        if extra:
            headers.update(extra)
        req = urllib.request.Request(base + path, data=raw, method=method, headers=headers)
        with urllib.request.urlopen(req, timeout=30) as response:
            body = response.read()
            return response.status, json.loads(body) if body else {}

    password = password_path.read_text(encoding="utf-8").strip()
    status, login = request_json(
        "POST", "/v1/auth/login", payload={"username": "admin", "password": password}
    )
    assert status == 200 and isinstance(login, dict)
    token = str(login["access_token"])
    status, project = request_json(
        "POST",
        "/v1/projects",
        payload={"title": "OPS-001N真实OCR", "mode": "document", "reading_order": "ltr"},
        token=token,
    )
    assert status == 201 and isinstance(project, dict)
    image = sample.read_bytes()
    digest = hashlib.sha256(image).hexdigest()
    status, upload = request_json(
        "POST",
        "/v1/uploads",
        payload={
            "project_id": project["id"],
            "file_name": sample.name,
            "mime_type": "image/png",
            "size_bytes": len(image),
            "sha256": digest,
            "idempotency_key": "ops001n-real-ocr-task",
        },
        token=token,
    )
    assert status == 201 and isinstance(upload, dict)
    chunk_size = int(upload["chunk_size"])
    for index, offset in enumerate(range(0, len(image), chunk_size)):
        chunk = image[offset : offset + chunk_size]
        status, _ = request_json(
            "PUT",
            f"/v1/uploads/{upload['id']}/chunks/{index}",
            raw=chunk,
            token=token,
            extra={"X-Chunk-SHA256": hashlib.sha256(chunk).hexdigest()},
        )
        assert status == 200
    status, page = request_json("POST", f"/v1/uploads/{upload['id']}/complete", token=token)
    assert status == 202 and isinstance(page, dict)
    deadline = time.monotonic() + 300
    while time.monotonic() < deadline:
        status, current = request_json("GET", f"/v1/pages/{page['id']}", token=token)
        assert status == 200 and isinstance(current, dict)
        if current.get("ocr_status") == "ready":
            assert str(current.get("ocr_text", "")).strip()
            return
        assert current.get("ocr_status") not in {"failed", "disabled"}
        time.sleep(2)
    raise AssertionError("真实OCR任务未在300秒内完成")


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
    source_root = CANDIDATE_ARCHIVES.stat()
    assert source_root.st_uid != 0, "CI发布归档应由普通Runner用户生成"
    deploy_uid = source_root.st_uid
    prepare_incremental_upload(deploy_uid)
    archive_root = ARCHIVES.stat()
    assert archive_root.st_uid != 0, "CI发布归档应模拟普通部署用户上传"
    ARCHIVES.chmod(0o700)
    for path in ARCHIVES.rglob("*"):
        if path.is_file():
            assert path.stat().st_uid == deploy_uid, f"归档所有者不一致：{path.name}"
            path.chmod(0o600)
    candidate_release = prepare_uploaded_candidate(deploy_uid)
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
        candidate_release=candidate_release,
        previous_release=CONFIG / "previous-release-manifest.json",
        previous_map=CONFIG / "previous-release-map.json",
        previous_local_images=CONFIG / "previous-local-images.env",
        previous_identities=CONFIG / "previous-image-identities.json",
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
    base_release = json.loads(paths.installed_release.read_text(encoding="utf-8"))
    base_worker = next(item for item in base_release["images"] if item["service"] == "worker")
    accepted = controller.accept_release()
    assert accepted["step"] == "incremental_release_accepted"
    assert json.loads(paths.installed_release.read_text(encoding="utf-8")) == base_release
    assert base_worker["local_tag"] in paths.local_images_env.read_text(encoding="utf-8")

    original_urlopen = uatctl.urllib.request.urlopen

    def isolated_daemon_internal_urlopen(url, *args, **kwargs):
        """隔离daemon禁用iptables时，通过固定nginx容器地址验证同一HTTP入口。"""

        if url != "http://127.0.0.1:18082/":
            return original_urlopen(url, *args, **kwargs)
        nginx_id = controller._compose("ps", "-q", "nginx").strip()
        assert nginx_id
        runtime = json.loads(controller.runner.run(["/usr/bin/docker", "inspect", nginx_id]))[0]
        address = runtime["NetworkSettings"]["Networks"]["smartscan-uat-edge"]["IPAddress"]
        assert address.startswith("172.30.11.")
        return original_urlopen(f"http://{address}/", *args, **kwargs)

    if CI_VARIANT == "legacy":
        uatctl.urllib.request.urlopen = isolated_daemon_internal_urlopen
    try:
        resumed = controller.resume_basic_uat()
    except uatctl.ControllerError:
        report_core_failure(controller)
        raise
    finally:
        uatctl.urllib.request.urlopen = original_urlopen
    assert resumed == {
        "status": "passed",
        "next_required": "stage-nginx",
        "secrets_included": False,
    }
    final = controller.status()
    assert final["next_required"] == "nginx_staged"
    assert {"core_started", "core_verified"}.issubset(final["completed"])
    assert not paths.active_nginx.exists()
    release, _ = controller._fixed_release()
    worker = next(item for item in release["images"] if item["service"] == "worker")
    assert worker["source"].endswith(
        "@sha256:9957b27924b0eb7ba6819c917a7b32ee2869a8b0bd560f2199f03e3232f3a742"
    )
    assert worker["local_tag"] != base_worker["local_tag"]
    assert controller.runner.run(
        ["/usr/bin/docker", "image", "inspect", "--format", "{{.Id}}", base_worker["local_tag"]]
    )
    running = set(controller._compose("ps", "--status", "running", "--services").splitlines())
    assert running == {
        "postgres",
        "api",
        "worker-cpu-1",
        "worker-cpu-2",
        "nginx",
        "loopback-proxy",
    }
    nginx_id = controller._compose("ps", "-q", "nginx").strip()
    nginx_runtime = json.loads(controller.runner.run(["/usr/bin/docker", "inspect", nginx_id]))[0]
    assert nginx_runtime["HostConfig"]["PortBindings"] == {}
    assert set(nginx_runtime["NetworkSettings"]["Networks"]) == {"smartscan-uat-edge"}
    proxy_id = controller._compose("ps", "-q", "loopback-proxy").strip()
    proxy_runtime = json.loads(controller.runner.run(["/usr/bin/docker", "inspect", proxy_id]))[0]
    assert proxy_runtime["HostConfig"]["PortBindings"]["8080/tcp"] == [
        {"HostIp": "127.0.0.1", "HostPort": "18082"}
    ]
    assert proxy_runtime["Mounts"] == []
    assert set(proxy_runtime["NetworkSettings"]["Networks"]) == {
        "smartscan-uat-edge",
        "smartscan-uat-publish",
    }
    assert not any(
        marker in item.split("=", 1)[0].upper()
        for item in proxy_runtime["Config"]["Env"]
        for marker in ("PASSWORD", "SECRET", "TOKEN", "DATABASE_URL")
    )
    web_routes = controller.runner.run(
        ["/usr/bin/docker", "exec", nginx_id, "cat", "/proc/net/route"]
    )
    assert not any(
        line.split()[1] == "00000000" for line in web_routes.splitlines()[1:] if line.split()
    )
    proxy_routes = controller.runner.run(
        ["/usr/bin/docker", "exec", proxy_id, "cat", "/proc/net/route"]
    )
    assert any(
        line.split()[1] == "00000000" for line in proxy_routes.splitlines()[1:] if line.split()
    )
    if CI_VARIANT == "containerd29":
        published = controller.runner.run(["/usr/bin/docker", "port", proxy_id, "8080/tcp"])
        assert published == "127.0.0.1:18082"
        with original_urlopen("http://127.0.0.1:18082/", timeout=5) as response:
            assert response.status == 200
        host_addresses = controller.runner.run(["/usr/bin/hostname", "-I"]).split()
        non_loopback = next(address for address in host_addresses if not address.startswith("127."))
        try:
            original_urlopen(f"http://{non_loopback}:18082/", timeout=2)
        except OSError:
            pass
        else:
            raise AssertionError("loopback_port_reachable_via_non_loopback_address")
    nginx_address = nginx_runtime["NetworkSettings"]["Networks"]["smartscan-uat-edge"]["IPAddress"]
    assert nginx_address.startswith("172.30.11.")
    worker_id = controller._compose("ps", "-q", "worker-cpu-1").strip()
    worker_runtime = json.loads(controller.runner.run(["/usr/bin/docker", "inspect", worker_id]))[0]
    assert worker_runtime["HostConfig"]["ReadonlyRootfs"] is True
    assert worker_runtime["HostConfig"]["CapDrop"] == ["ALL"]
    assert any(
        item.startswith("no-new-privileges") for item in worker_runtime["HostConfig"]["SecurityOpt"]
    )
    assert worker_runtime["HostConfig"]["NanoCpus"] == 1_250_000_000
    assert worker_runtime["HostConfig"]["Memory"] == 2 * GIB
    assert worker_runtime["HostConfig"]["PidsLimit"] == 256
    assert set(worker_runtime["HostConfig"]["Tmpfs"]) == {"/tmp"}
    assert set(worker_runtime["NetworkSettings"]["Networks"]) == {"smartscan-uat-data"}
    assert any(item == "HOME=/tmp/smartscan-home" for item in worker_runtime["Config"]["Env"])
    model_mount = next(
        item
        for item in worker_runtime["Mounts"]
        if item["Destination"] == "/opt/smartscan/models/ocr"
    )
    assert model_mount["RW"] is False
    library_check = controller._compose(
        "exec",
        "-T",
        "worker-cpu-1",
        "python",
        "-c",
        (
            "import ctypes,cv2; "
            "ctypes.CDLL('libGL.so.1'); ctypes.CDLL('libgthread-2.0.so.0'); "
            "ctypes.CDLL('libgomp.so.1'); "
            "print('worker_libraries=passed')"
        ),
    )
    assert library_check == "worker_libraries=passed"
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
    samples = Path(os.environ["SMARTSCAN_REAL_OCR_SAMPLES"])
    sample = next(path for path in sorted(samples.iterdir()) if path.name.startswith("zh-cn"))
    http_origin = f"http://{nginx_address}"
    verify_real_worker_task(
        paths.config_root / "bootstrap-admin-password",
        sample,
        origin=http_origin,
    )
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
