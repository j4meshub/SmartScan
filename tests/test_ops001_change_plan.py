from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_ops001_plan_records_accepted_loop_and_remains_fail_closed() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")

    assert "loop存储门禁已通过，应用部署未执行" in plan
    assert "两次独立`verify`" in plan
    assert "recreate-empty" in plan
    assert "nodiscard,lazy_itable_init=0,lazy_journal_init=0" in plan
    assert "不得直接部署这组镜像" in plan
    assert "0961cc3" in plan
    assert "`/api`" in plan
    assert "`/smartscan/api`" in plan
    assert "新主线镜像不得自动替换" in plan
    assert "192.168." not in plan


def test_ops001_candidate_evidence_is_complete_and_acceptance_is_recorded() -> None:
    evidence = (ROOT / "docs" / "2ADBF4F_CONTAINER_VERIFICATION.md").read_text(encoding="utf-8")
    plan = (ROOT / "docs" / "CODEX_EXECUTION_PLAN.md").read_text(encoding="utf-8")

    for digest in (
        "80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0",
        "f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6",
        "1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00",
        "3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c",
        "be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae",
    ):
        assert digest in evidence
    assert "2adbf4f3a000a0fc57aa76b1bff0faa5b99b2697" in evidence
    assert "可修复High/Critical为0" in evidence
    assert "用户已接受本文件中的五个固定digest" in evidence
    assert "接受不授权拉取或部署" in evidence
    assert "OPS-REG-003B" in evidence
    assert "`OPS-REG-003B` 可审计PostgreSQL 17运行镜像 | 完成" in plan
    assert "`OPS-001D` 应用部署前最终只读预检 | 完成" in plan
    assert "`OPS-001` 共享主机验收栈 | 等待人工验收" in plan
    assert "192.168." not in evidence


def test_ops001_plan_contains_fixed_artifacts_and_boundaries() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")
    candidate_config = (ROOT / "deploy" / "compose" / "uat.env.example").read_text(encoding="utf-8")
    accepted_digests = (
        "94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0",
        "80aea0a272791ea44d76895dbd825d091620e0f43ad76c32f32fb6ba97c646d0",
        "f1cb15e434e99fdced69885667e8646346c75bc293e8ecf9f6b0fa24951768a6",
        "1813ada8bda225530d71e5afa9e1c3fd640d5e23d05000d370fdccad0e5e8b00",
        "3d701a4bcaf24c03ead231f10abd316ba83ab89a6984894dfe31af404d3c930c",
        "be6c50fbdbc9404a9d9589a53799dbc6084470a63f2306ec6bee5736adf94cae",
    )

    for digest in accepted_digests:
        assert digest in candidate_config
    assert "526f86d93c6ea08fd3f1fe5605650cacc781b2c6013169a0ad8f42c7d3d84f32" in plan
    assert "/etc/nginx/snippets/smartscan-uat-8077.locations.conf" in plan
    assert "127.0.0.1:18082" in plan
    assert "/smartscan/api/v1/" in plan
    assert "50 GiB" in plan
    assert "8 vCPU/16 GiB" in plan
    for network_name in ("smartscan-uat-data", "smartscan-uat-edge", "smartscan-uat-egress"):
        assert network_name in plan
        assert f"name: ${{COMPOSE_PROJECT_NAME}}-{network_name.removeprefix('smartscan-uat-')}" in (
            ROOT / "deploy" / "compose" / "docker-compose.uat.yml"
        ).read_text(encoding="utf-8")


def test_ops001_final_preflight_is_sanitized_and_does_not_grant_deployment() -> None:
    evidence = (ROOT / "docs" / "OPS001_FINAL_READONLY_PREFLIGHT_20261120.md").read_text(
        encoding="utf-8"
    )
    progress = (ROOT / "docs" / "CODEX_PROGRESS.md").read_text(encoding="utf-8")

    assert "OPS-001D" in evidence
    assert "linux/amd64" in evidence
    assert "USER 70:70" in evidence
    assert "PostgreSQL 17.12" in evidence
    assert "不授权创建目录、Secret、Docker网络或容器" in evidence
    assert "94758173bbe1975014751a2e2855a22e0e554e8df996e4d6303bcf386cdae6d0" in progress
    assert "e54319a0ae69c22731599fb942500e942e5ba03d34c32406a3d747bffcefd04b" in progress
    for sensitive_fragment in ("192.168.", "10.254.240.", "/dev/loop"):
        assert sensitive_fragment not in evidence


def test_ops001_plan_contains_safe_rollback_and_authorization() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")

    assert "nginx -t" in plan
    assert "不带`-v`" in plan
    assert "不提供自动降级" in plan
    assert "禁止任何prune" in plan
    assert "最终授权点" in plan
    assert "HTTP IP入口不能通过`getUserMedia`实时相机" in plan
