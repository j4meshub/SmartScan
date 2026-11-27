from __future__ import annotations

import json
from pathlib import Path

import pytest
import yaml

from tools.validate_uat_config import (
    ACCEPTED_UAT_IMAGES,
    DEFAULT_COMPOSE_FILE,
    UatConfigError,
    _validate_digest_image,
    validate_uat_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uat"
LOOP_EVIDENCE = FIXTURES / "loop-storage-evidence.json"
MOUNT_UNIT_TEMPLATE = (
    Path(__file__).parents[1] / "deploy" / "systemd" / "mnt-data-smartscan-uat.mount.template"
)
SHARED_NGINX_TEMPLATE = (
    Path(__file__).parents[1] / "deploy" / "nginx" / "shared-8077-smartscan-location.conf.template"
)
WORKER_DOCKERFILE = Path(__file__).parents[1] / "services" / "worker" / "Dockerfile"


def _write_changed(source: Path, target: Path, old: str, new: str) -> Path:
    target.write_text(source.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return target


def _validate(
    tmp_path: Path,
    *,
    deploy: Path | None = None,
    runtime: Path | None = None,
    allocation: Path | None = None,
    loop_evidence: Path | None = None,
    compose: Path | None = None,
    mount_unit: Path | None = None,
):
    return validate_uat_config(
        deploy or FIXTURES / "deploy.env",
        runtime or FIXTURES / "runtime.env",
        allocation or FIXTURES / "allocation.json",
        loop_evidence or LOOP_EVIDENCE,
        compose_file=compose or DEFAULT_COMPOSE_FILE,
        mount_unit_file=mount_unit or MOUNT_UNIT_TEMPLATE,
        ci_fixture=True,
    )


def test_valid_fixture_returns_secret_free_summary(tmp_path: Path) -> None:
    result = _validate(tmp_path)

    summary = result.safe_summary()
    serialized = json.dumps(summary, ensure_ascii=False)
    assert summary["project_name"] == "smartscan-uat"
    assert summary["http_bind"] == "127.0.0.1:18082"
    assert len(summary["image_digests"]) == 6
    assert summary["secrets_included"] is False
    assert "ci-only-uat-database-password" not in serialized
    assert "SMARTSCAN_SECRET_KEY" not in serialized


def test_worker_image_installs_required_headless_visual_runtime_library() -> None:
    dockerfile = WORKER_DOCKERFILE.read_text(encoding="utf-8")

    assert "apt-get install -y --no-install-recommends libgl1 libglib2.0-0t64" in dockerfile


def test_worker_runtime_cache_is_bounded_by_existing_tmpfs() -> None:
    root = Path(__file__).parents[1]
    compose = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")
    workflow = (root / ".github" / "workflows" / "container-publish.yml").read_text(
        encoding="utf-8"
    )

    assert "HOME: /tmp/smartscan-home" in compose
    assert "--env HOME=/tmp/smartscan-home" in workflow
    assert "/tmp:rw,noexec,nosuid,nodev,size=512m" in compose
    worker = compose.split("\n  worker-cpu-1:", 1)[1].split("\n  worker-cpu-2:", 1)[0]
    assert 'cap_drop: ["ALL"]' in worker


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "SMARTSCAN_UAT_DATA_SUBNET=172.30.10.0/24",
            "SMARTSCAN_UAT_DATA_SUBNET=172.31.10.0/24",
            "data 网络不一致",
        ),
        (
            "SMARTSCAN_UAT_HTTP_PORT=18082",
            "SMARTSCAN_UAT_HTTP_PORT=443",
            "监听端口与资源确认不一致",
        ),
        (
            "SMARTSCAN_UAT_DATA_ROOT=/mnt/data/smartscan/uat/data",
            "SMARTSCAN_UAT_DATA_ROOT=/srv/smartscan/staging/data",
            "必须位于 /mnt/data/smartscan/uat 下",
        ),
        (
            "ghcr.io/j4meshub/smartscan-api@sha256:",
            "registry.example.invalid/smartscan-api@sha256:",
            "必须使用批准的 GHCR 仓库",
        ),
    ],
)
def test_deploy_configuration_must_match_approved_boundaries(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    deploy = _write_changed(FIXTURES / "deploy.env", tmp_path / "deploy.env", old, new)

    with pytest.raises(UatConfigError, match=message):
        _validate(tmp_path, deploy=deploy)


def test_postgres_image_must_use_smartscan_ghcr_repository(tmp_path: Path) -> None:
    deploy = _write_changed(
        FIXTURES / "deploy.env",
        tmp_path / "deploy.env",
        "ghcr.io/j4meshub/smartscan-postgres@sha256:",
        "docker.io/library/postgres@sha256:",
    )

    with pytest.raises(UatConfigError, match="批准的 GHCR 仓库"):
        _validate(tmp_path, deploy=deploy)


def test_allocation_requires_hard_storage_limit(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["storage"]["hard_limit_confirmed"] = False
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="硬限制尚未确认"):
        _validate(tmp_path, allocation=path)


def test_allocation_rejects_public_bind_address(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["host_ports"][0]["bind_address"] = "8.8.8.8"
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")
    deploy = _write_changed(
        FIXTURES / "deploy.env",
        tmp_path / "deploy.env",
        "SMARTSCAN_UAT_BIND_ADDRESS=127.0.0.1",
        "SMARTSCAN_UAT_BIND_ADDRESS=8.8.8.8",
    )

    with pytest.raises(UatConfigError, match="127.0.0.1"):
        _validate(tmp_path, deploy=deploy, allocation=path)


def test_allocation_rejects_duplicate_node_exporter_plan(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["monitoring"]["deploy_node_exporter"] = True
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="禁止部署 Node Exporter"):
        _validate(tmp_path, allocation=path)


def test_allocation_rejects_second_host_port(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["host_ports"].append(
        {"purpose": "内部指标入口", "port": 19081, "bind_address": "127.0.0.1"}
    )
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="只能申请一个"):
        _validate(tmp_path, allocation=path)


def test_allocation_requires_fixed_storage_thresholds(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["storage"]["quota_bytes"] = 100 * 1024**3
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="50 GiB"):
        _validate(tmp_path, allocation=path)


def test_allocation_requires_storage_budgets_to_fit_hard_limit(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["storage_budgets"]["business_data_bytes"] += 1024**3
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="业务文件预算"):
        _validate(tmp_path, allocation=path)


def test_runtime_business_quota_must_match_storage_budget(tmp_path: Path) -> None:
    runtime = _write_changed(
        FIXTURES / "runtime.env",
        tmp_path / "runtime.env",
        "SMARTSCAN_STORAGE_QUOTA_BYTES=34359738368",
        "SMARTSCAN_STORAGE_QUOTA_BYTES=53687091200",
    )

    with pytest.raises(UatConfigError, match="业务文件预算"):
        _validate(tmp_path, runtime=runtime)


def test_runtime_uses_loop_local_reserve_not_host_reserve(tmp_path: Path) -> None:
    runtime = _write_changed(
        FIXTURES / "runtime.env",
        tmp_path / "runtime.env",
        "SMARTSCAN_STORAGE_MIN_FREE_BYTES=2147483648",
        "SMARTSCAN_STORAGE_MIN_FREE_BYTES=214748364800",
    )

    with pytest.raises(UatConfigError, match="应用内绝对预留必须为 2 GiB"):
        _validate(tmp_path, runtime=runtime)


@pytest.mark.parametrize(
    ("key", "repository", "digest"),
    [
        (
            "SMARTSCAN_UAT_WEB_IMAGE",
            "ghcr.io/j4meshub/smartscan-web",
            "44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915",
        ),
        (
            "SMARTSCAN_UAT_OPS_IMAGE",
            "ghcr.io/j4meshub/smartscan-ops",
            "ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b",
        ),
    ],
)
def test_known_incompatible_uat_images_fail_closed(key: str, repository: str, digest: str) -> None:
    with pytest.raises(UatConfigError, match="已知不兼容"):
        _validate_digest_image(
            f"{repository}@sha256:{digest}",
            key,
            repository=repository,
            ci_fixture=False,
        )


def test_real_uat_config_accepts_only_user_accepted_fixed_digests() -> None:
    for key, value in ACCEPTED_UAT_IMAGES.items():
        repository = value.rsplit("@sha256:", 1)[0]
        assert _validate_digest_image(
            value,
            key,
            repository=repository,
            ci_fixture=False,
        )

        changed = value[:-1] + ("0" if value[-1] != "0" else "1")
        with pytest.raises(UatConfigError, match="不是用户已接受"):
            _validate_digest_image(
                changed,
                key,
                repository=repository,
                ci_fixture=False,
            )


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('restart: "no"', "restart: unless-stopped", "禁止自动重启"),
        ('cpus: "1.50"', 'cpus: "0"', "缺少 CPU 限制"),
        ('max-size: "10m"', 'max-size: ""', "日志必须精确限制为10m×3"),
        (
            "gateway: ${SMARTSCAN_UAT_DATA_GATEWAY:?必须设置批准的 data 网关}",
            "missing: ${SMARTSCAN_UAT_DATA_GATEWAY:?禁止自动网段}",
            "data 网络禁止自动分配 CIDR",
        ),
    ],
)
def test_compose_rejects_unsafe_runtime_contract(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    compose = _write_changed(DEFAULT_COMPOSE_FILE, tmp_path / "compose.yml", old, new)

    with pytest.raises(UatConfigError, match=message):
        _validate(tmp_path, compose=compose)


def test_compose_rejects_source_build_and_host_root_mount(tmp_path: Path) -> None:
    source = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")
    source = source.replace(
        "  postgres:\n    image:",
        "  postgres:\n    build: .\n    image:",
        1,
    )
    compose = tmp_path / "compose.yml"
    compose.write_text(source, encoding="utf-8")

    with pytest.raises(UatConfigError, match="禁止在服务器现场构建"):
        _validate(tmp_path, compose=compose)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ("  read_only: true\n", "  read_only: false\n", "根文件系统必须只读"),
        (
            "/tmp:rw,noexec,nosuid,nodev,size=64m,mode=1777",
            "/tmp:rw,noexec,nosuid,nodev,mode=1777",
            "tmpfs边界无效",
        ),
        ('options: {max-size: "10m", max-file: "3"}', 'options: {max-size: "10m"}', "10m×3"),
    ],
)
def test_compose_rejects_unbounded_writable_layers(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    compose = _write_changed(DEFAULT_COMPOSE_FILE, tmp_path / "compose.yml", old, new)

    with pytest.raises(UatConfigError, match=message):
        _validate(tmp_path, compose=compose)


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        (
            "SMARTSCAN_STORAGE_ROOT: /tmp/smartscan-data",
            "SMARTSCAN_STORAGE_ROOT: /srv/smartscan/data",
            "migrate 临时storage root无效",
        ),
        ("    logging:\n      driver: none", "    logging:\n      driver: json-file", "禁止持久化"),
    ],
)
def test_migrate_service_rejects_real_storage_or_persistent_logs(
    tmp_path: Path, old: str, new: str, message: str
) -> None:
    compose = _write_changed(DEFAULT_COMPOSE_FILE, tmp_path / "compose.yml", old, new)

    with pytest.raises(UatConfigError, match=message):
        _validate(tmp_path, compose=compose)


def test_compose_rejects_postgres_socket_named_volume(tmp_path: Path) -> None:
    source = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")
    source += "\nvolumes:\n  postgres-socket:\n"
    compose = tmp_path / "compose.yml"
    compose.write_text(source, encoding="utf-8")

    with pytest.raises(UatConfigError, match="socket named volume"):
        _validate(tmp_path, compose=compose)


def test_compose_rejects_postgres_root_runtime(tmp_path: Path) -> None:
    compose = _write_changed(
        DEFAULT_COMPOSE_FILE,
        tmp_path / "compose.yml",
        '    user: "70:70"',
        '    user: "0:0"',
    )

    with pytest.raises(UatConfigError, match="UID/GID 70:70"):
        _validate(tmp_path, compose=compose)


def test_compose_rejects_postgres_locale_drift(tmp_path: Path) -> None:
    compose = _write_changed(
        DEFAULT_COMPOSE_FILE,
        tmp_path / "compose.yml",
        "POSTGRES_INITDB_ARGS: --encoding=UTF8 --locale=C",
        "POSTGRES_INITDB_ARGS: --encoding=SQL_ASCII --locale=C",
    )

    with pytest.raises(UatConfigError, match="UTF-8 初始化参数"):
        _validate(tmp_path, compose=compose)


def test_loop_evidence_digest_must_match_deploy_record(tmp_path: Path) -> None:
    deploy = _write_changed(
        FIXTURES / "deploy.env",
        tmp_path / "deploy.env",
        "da0ce50c769c515d25dca9b1b4a3ec5a3bf74a9f28db438f743a652477717ccb",
        "0" * 64,
    )

    with pytest.raises(UatConfigError, match="loop存储证据摘要"):
        _validate(tmp_path, deploy=deploy)


def test_runtime_keeps_external_services_disabled(tmp_path: Path) -> None:
    runtime = _write_changed(
        FIXTURES / "runtime.env",
        tmp_path / "runtime.env",
        "SMARTSCAN_AI_PROVIDERS=[]",
        'SMARTSCAN_AI_PROVIDERS=[{"id":"forbidden"}]',
    )

    with pytest.raises(UatConfigError, match="必须关闭外部 AI"):
        _validate(tmp_path, runtime=runtime)


def test_resource_totals_cannot_exceed_allocation(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["resources"]["cpu_limit"] = 2
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="CPU 上限必须为 8"):
        _validate(tmp_path, allocation=path)


def test_uat_compose_has_expected_base_and_ai_resource_totals(tmp_path: Path) -> None:
    _validate(tmp_path)
    document = DEFAULT_COMPOSE_FILE.read_text(encoding="utf-8")

    assert "SMARTSCAN_UAT_WAL_ROOT" not in document
    assert "archive_command" not in document


def test_web_and_loopback_proxy_keep_separate_network_and_security_boundaries() -> None:
    root = Path(__file__).parents[1]
    compose = yaml.safe_load(
        (root / "deploy/compose/docker-compose.uat.yml").read_text(encoding="utf-8")
    )
    services = compose["services"]
    web = services["nginx"]
    proxy = services["loopback-proxy"]

    assert web["networks"] == ["edge"]
    assert "ports" not in web
    assert len(web["volumes"]) == 1 and web["volumes"][0]["read_only"] is True
    assert proxy["user"] == "101:101"
    assert proxy["cap_drop"] == ["ALL"]
    assert proxy["read_only"] is True
    assert "volumes" not in proxy and "env_file" not in proxy and "environment" not in proxy
    assert set(proxy["networks"]) == {"edge", "publish"}
    assert proxy["ports"] == [
        (
            "${SMARTSCAN_UAT_BIND_ADDRESS:?必须设置批准的监听地址}:"
            "${SMARTSCAN_UAT_HTTP_PORT:?必须设置批准的 UAT 端口}:8080"
        )
    ]
    assert compose["networks"]["edge"]["internal"] is True
    assert compose["networks"]["publish"] == {
        "name": "${COMPOSE_PROJECT_NAME}-publish",
        "external": True,
    }


def test_web_nginx_uses_one_worker_and_proxy_has_fixed_internal_upstream() -> None:
    root = Path(__file__).parents[1]
    web = (root / "deploy/nginx/nginx.conf").read_text(encoding="utf-8")
    proxy = (root / "deploy/nginx/loopback-proxy.conf").read_text(encoding="utf-8")

    assert web.startswith("worker_processes 1;\n")
    assert "worker_processes auto" not in web
    assert "worker_processes 1;" in proxy
    assert "listen 8080 default_server;" in proxy
    assert "server nginx:80;" in proxy
    assert "proxy_pass http://smartscan_internal_web;" in proxy


def test_shared_nginx_template_is_limited_to_smartscan_path_and_loopback_upstream() -> None:
    document = SHARED_NGINX_TEMPLATE.read_text(encoding="utf-8")

    assert "location = /smartscan" in document
    assert "return 308 /smartscan/;" in document
    assert "location ^~ /smartscan/" in document
    assert "proxy_pass http://127.0.0.1:18082/;" in document
    assert "location = /smartscan/api/internal/metrics" in document
    assert "proxy_request_buffering off;" in document
    assert "proxy_buffering off;" in document
    assert "client_max_body_size 26m;" in document
    assert "listen " not in document
    assert "server {" not in document
    assert "19081" not in document
