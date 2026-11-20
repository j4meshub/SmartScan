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


def test_ops001_candidate_evidence_is_complete_and_accepted_without_deploy_auth() -> None:
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
    assert "用户已经明确接受" in evidence
    assert "不授权服务器拉取" in evidence
    assert "OPS-REG-003" in evidence
    assert "`OPS-REG-003` 官方PostgreSQL固定digest GHCR供应链 | 进行中" in plan
    assert "192.168." not in evidence


def test_ops001_plan_contains_fixed_artifacts_and_boundaries() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")
    accepted_digests = (
        "b4f97968a81777c9b46bcae272be5153df796cfd4b2f9221008facc53358300a",
        "0dc0fe0de3e4518985bd906a08815b70419d86d5530e300a216d25a221ad07f7",
        "8e7af7bf3d23687c19ecdd10b85044eee8321a019f831bb7744ce2575fc0518c",
        "44a0faf547140844eb065a65034d442b66dd9f971ae5521b8a97400bd50df915",
        "ef4dd40c7b8a494e92540dc5bb476ab144903402142a0bbb0fdc4fd688138a5b",
    )

    for digest in accepted_digests:
        assert digest in plan
    assert "0d938e975177bef9f1f61f3f9dbcf2e0aa0a139568f66d3415ed8892eb97f6ac" in plan
    assert "/etc/nginx/snippets/smartscan-uat-8077.locations.conf" in plan
    assert "127.0.0.1:18082" in plan
    assert "/smartscan/api/v1/" in plan
    assert "50 GiB" in plan
    assert "8 vCPU/16 GiB" in plan


def test_ops001_plan_contains_safe_rollback_and_authorization() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")

    assert "nginx -t" in plan
    assert "不带`-v`" in plan
    assert "不提供自动降级" in plan
    assert "禁止任何prune" in plan
    assert "最终授权点" in plan
    assert "HTTP IP入口不能通过`getUserMedia`实时相机" in plan
