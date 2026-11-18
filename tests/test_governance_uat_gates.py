from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).parents[1]


def read(path: str) -> str:
    return (ROOT / path).read_text(encoding="utf-8")


def test_active_governance_uses_shared_server_user_confirmation() -> None:
    execution = read("docs/CODEX_EXECUTION_PLAN.md")
    decisions = read("docs/DECISIONS.md")
    deployment = read("docs/SHARED_HOST_DEPLOYMENT.md")

    assert "GOV-005" in execution
    assert "`OPS-000` 共享宿主机预检与资源分配 | 完成" in execution
    assert "D-085" in decisions
    assert "服务器共同使用人" in deployment
    assert "等待 OPS-000 资源/窗口审批" not in execution
    assert "OPS-003 共租户监控接入后执行" not in execution
    assert "| UAT 存储 | 100 GiB" not in deployment
    assert "| 生产存储 | 500 GiB" not in deployment


def test_uat_allocation_template_encodes_current_fixed_boundaries() -> None:
    allocation = json.loads(read("deploy/compose/shared-host-allocation.example.json"))

    assert allocation["schema_version"] == "1.2"
    assert "approval" not in allocation
    assert set(allocation["confirmation"]) == {
        "confirmed_by",
        "confirmed_at",
        "change_record",
        "validation_record",
        "rollback_record",
    }
    assert allocation["host_ports"] == [
        {
            "purpose": "UAT Web 回环入口",
            "port": 18082,
            "bind_address": "127.0.0.1",
        }
    ]
    assert allocation["storage"]["quota_bytes"] == 50 * 1024**3
    assert allocation["storage_budgets"] == {
        "postgres_and_wal_bytes": 12 * 1024**3,
        "business_data_bytes": 32 * 1024**3,
        "ocr_models_bytes": 4 * 1024**3,
        "container_logs_bytes": 1024**3,
        "reserve_bytes": 1024**3,
    }
    assert (
        allocation["storage"]["warning_percent"],
        allocation["storage"]["cleanup_percent"],
        allocation["storage"]["stop_writes_percent"],
    ) == (70, 85, 95)
    assert allocation["resources"] == {
        "cpu_limit": 8,
        "memory_limit_bytes": 16 * 1024**3,
    }
    assert allocation["ingress"]["shared_nginx_port"] == 8077
    assert allocation["ingress"]["base_path"] == "/smartscan/"
    assert allocation["monitoring"]["deploy_node_exporter"] is False
    assert allocation["monitoring"]["deploy_alertmanager"] is False
    assert allocation["backup"]["required"] is False


def test_active_uat_templates_have_no_wal_archive_or_second_host_port() -> None:
    compose = read("deploy/compose/docker-compose.uat.yml")
    deploy = read("deploy/compose/uat.env.example")
    nginx = read("deploy/nginx/shared-8077-smartscan-location.conf.template")

    assert "SMARTSCAN_UAT_WAL_ROOT" not in compose
    assert "archive_command" not in compose
    assert "SMARTSCAN_UAT_HTTP_PORT=18082" in deploy
    assert "19081" not in deploy
    assert "proxy_pass http://127.0.0.1:18082/;" in nginx
    assert "listen " not in nginx
