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
    assert summary["http_bind"] == "127.0.0.1:18081"
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
            "SMARTSCAN_UAT_HTTP_PORT=18081",
            "SMARTSCAN_UAT_HTTP_PORT=443",
            "监听端口与资源审批不一致",
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

    with pytest.raises(UatConfigError, match="回环或批准的私网地址"):
        _validate(tmp_path, deploy=deploy, allocation=path)


def test_allocation_rejects_duplicate_node_exporter_plan(tmp_path: Path) -> None:
    allocation = json.loads((FIXTURES / "allocation.json").read_text(encoding="utf-8"))
    allocation["monitoring"]["deploy_node_exporter"] = True
    path = tmp_path / "allocation.json"
    path.write_text(json.dumps(allocation), encoding="utf-8")

    with pytest.raises(UatConfigError, match="禁止重复 Node Exporter"):
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

    with pytest.raises(UatConfigError, match="CPU 限制总和超过资源审批"):
        _validate(tmp_path, allocation=path)
