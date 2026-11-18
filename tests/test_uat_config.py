from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.validate_uat_config import (
    DEFAULT_COMPOSE_FILE,
    UatConfigError,
    validate_uat_config,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uat"
SHARED_NGINX_TEMPLATE = (
    Path(__file__).parents[1] / "deploy" / "nginx" / "shared-8077-smartscan-location.conf.template"
)


def _write_changed(source: Path, target: Path, old: str, new: str) -> Path:
    target.write_text(source.read_text(encoding="utf-8").replace(old, new), encoding="utf-8")
    return target


def _validate(
    tmp_path: Path,
    *,
    deploy: Path | None = None,
    runtime: Path | None = None,
    allocation: Path | None = None,
    compose: Path | None = None,
):
    return validate_uat_config(
        deploy or FIXTURES / "deploy.env",
        runtime or FIXTURES / "runtime.env",
        allocation or FIXTURES / "allocation.json",
        compose_file=compose or DEFAULT_COMPOSE_FILE,
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


@pytest.mark.parametrize(
    ("old", "new", "message"),
    [
        ('restart: "no"', "restart: unless-stopped", "禁止自动重启"),
        ('cpus: "1.50"', 'cpus: "0"', "缺少 CPU 限制"),
        ('max-size: "10m"', 'max-size: ""', "缺少日志轮转限制"),
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
