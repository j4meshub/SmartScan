from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.validate_uat_loop_storage import (
    GIB,
    LoopStorageError,
    validate_loop_storage_evidence,
    validate_loop_storage_plan,
)

FIXTURES = Path(__file__).parent / "fixtures" / "uat"
ALLOCATION = FIXTURES / "allocation.json"
EVIDENCE = FIXTURES / "loop-storage-evidence.json"
MOUNT_UNIT = (
    Path(__file__).parents[1] / "deploy" / "systemd" / "mnt-data-smartscan-uat.mount.template"
)


def _write_json(tmp_path: Path, source: Path, mutate) -> Path:
    document = json.loads(source.read_text(encoding="utf-8"))
    mutate(document)
    target = tmp_path / source.name
    target.write_text(json.dumps(document), encoding="utf-8")
    return target


def test_loop_plan_and_created_evidence_pass() -> None:
    plan = validate_loop_storage_plan(ALLOCATION, MOUNT_UNIT)
    created = validate_loop_storage_evidence(
        ALLOCATION,
        MOUNT_UNIT,
        EVIDENCE,
        ci_fixture=True,
    )

    assert plan.mode == "plan"
    assert plan.business_data_bytes == 32 * GIB
    assert created.mode == "created"
    assert created.usable_bytes == 52_000_000_000
    assert created.safe_summary()["contains_secrets"] is False


@pytest.mark.parametrize(
    ("mutate", "message"),
    [
        (
            lambda document: document["backing_file"].update(size_bytes=49 * GIB),
            "精确为50 GiB",
        ),
        (
            lambda document: document["backing_file"].update(allocated_bytes=49 * GIB, sparse=True),
            "完整预分配",
        ),
        (
            lambda document: document["mount"].update(options=["loop", "nodev"]),
            "实际挂载缺少",
        ),
        (
            lambda document: document["filesystem"].update(usable_bytes=47 * GIB),
            "必须降低业务文件预算",
        ),
        (
            lambda document: document["loop"].update(autoclear=False),
            "autoclear",
        ),
    ],
)
def test_loop_evidence_rejects_unsafe_facts(tmp_path: Path, mutate, message: str) -> None:
    evidence = _write_json(tmp_path, EVIDENCE, mutate)

    with pytest.raises(LoopStorageError, match=message):
        validate_loop_storage_evidence(
            ALLOCATION,
            MOUNT_UNIT,
            evidence,
            ci_fixture=True,
        )


def test_lower_business_budget_can_match_lower_usable_space(tmp_path: Path) -> None:
    allocation = _write_json(
        tmp_path,
        ALLOCATION,
        lambda document: document["storage_budgets"].update(
            business_data_bytes=31 * GIB,
            filesystem_and_runtime_bytes=3 * GIB,
        ),
    )
    evidence = _write_json(
        tmp_path,
        EVIDENCE,
        lambda document: document["filesystem"].update(usable_bytes=47 * GIB),
    )

    result = validate_loop_storage_evidence(
        allocation,
        MOUNT_UNIT,
        evidence,
        ci_fixture=True,
    )

    assert result.business_data_bytes == 31 * GIB
    assert result.usable_bytes == 47 * GIB


def test_creation_plan_requires_explicit_hard_limit_confirmation(tmp_path: Path) -> None:
    allocation = _write_json(
        tmp_path,
        ALLOCATION,
        lambda document: document["storage"].update(hard_limit_confirmed=False),
    )

    with pytest.raises(LoopStorageError, match="尚未由共同使用人确认"):
        validate_loop_storage_plan(allocation, MOUNT_UNIT)


def test_mount_unit_requires_parent_mount_dependency_and_rollback(tmp_path: Path) -> None:
    target = tmp_path / "mnt-data-smartscan-uat.mount"
    target.write_text(
        MOUNT_UNIT.read_text(encoding="utf-8")
        .replace("# 回滚：", "# 撤销：")
        .replace("RequiresMountsFor=/mnt/data\n", ""),
        encoding="utf-8",
    )

    with pytest.raises(LoopStorageError, match="回滚说明"):
        validate_loop_storage_plan(ALLOCATION, target)
