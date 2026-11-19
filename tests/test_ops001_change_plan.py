from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).parents[1]


def test_ops001_plan_records_partial_loop_and_remains_fail_closed() -> None:
    plan = (ROOT / "docs" / "OPS001_UAT_CHANGE_PLAN.md").read_text(encoding="utf-8")

    assert "loop首次创建已执行但独立验证失败，应用部署未执行" in plan
    assert "backing_sparse" in plan
    assert "recreate-empty" in plan
    assert "nodiscard,lazy_itable_init=0,lazy_journal_init=0" in plan
    assert "不得直接部署这组镜像" in plan
    assert "0961cc3" in plan
    assert "`/api`" in plan
    assert "`/smartscan/api`" in plan
    assert "新主线镜像不得自动替换" in plan
    assert "192.168." not in plan


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
