"""验证 SmartScan UAT loop ext4 计划与创建后脱敏证据，不修改服务器。"""

from __future__ import annotations

import argparse
import configparser
import hashlib
import json
import re
from dataclasses import dataclass
from pathlib import Path
from typing import Any

GIB = 1024**3
BACKING_FILE = "/mnt/data/smartscan-loop/uat.ext4"
MOUNT_POINT = "/mnt/data/smartscan/uat"
UNIT_NAME = "mnt-data-smartscan-uat.mount"
UNIT_INSTALL_PATH = f"/etc/systemd/system/{UNIT_NAME}"
REQUIRED_MOUNT_OPTIONS = frozenset({"loop", "nodev", "nosuid", "noatime"})
REQUIRED_RUNTIME_MOUNT_OPTIONS = frozenset({"nodev", "nosuid", "noatime"})
PLACEHOLDER_WORDS = ("replace", "placeholder", "待填写", "待确认")


class LoopStorageError(ValueError):
    """loop存储计划或证据不满足失败关闭边界。"""


@dataclass(frozen=True)
class LoopStorageResult:
    mode: str
    allocation_sha256: str
    unit_sha256: str
    evidence_sha256: str | None
    business_data_bytes: int
    usable_bytes: int | None

    def safe_summary(self) -> dict[str, Any]:
        return {
            "schema_version": "1.0",
            "status": "passed",
            "mode": self.mode,
            "allocation_sha256": self.allocation_sha256,
            "unit_sha256": self.unit_sha256,
            "evidence_sha256": self.evidence_sha256,
            "business_data_bytes": self.business_data_bytes,
            "usable_bytes": self.usable_bytes,
            "contains_paths": False,
            "contains_secrets": False,
        }


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LoopStorageError(message)


def _load_json(path: Path, label: str) -> tuple[dict[str, Any], str]:
    try:
        raw = path.read_bytes()
        document = json.loads(raw)
    except (OSError, json.JSONDecodeError) as exc:
        raise LoopStorageError(f"无法读取{label}：{path}") from exc
    _require(isinstance(document, dict), f"{label}根节点必须是对象")
    return document, hashlib.sha256(raw).hexdigest()


def _has_placeholder(value: str) -> bool:
    lowered = value.casefold()
    return any(word in lowered for word in PLACEHOLDER_WORDS)


def _storage_contract(allocation: dict[str, Any]) -> tuple[dict[str, Any], int]:
    _require(allocation.get("schema_version") == "1.2", "资源确认版本必须为1.2")
    storage = allocation.get("storage")
    _require(isinstance(storage, dict), "资源确认缺少storage")
    _require(storage.get("root") == MOUNT_POINT, "UAT挂载点无效")
    _require(storage.get("quota_bytes") == 50 * GIB, "loop后备文件边界必须为50 GiB")
    _require(storage.get("hard_limit_type") == "loop_ext4", "硬限制类型必须为loop_ext4")
    _require(storage.get("hard_limit_confirmed") is True, "loop硬限制尚未由共同使用人确认")

    budgets = allocation.get("storage_budgets")
    _require(isinstance(budgets, dict), "资源确认缺少storage_budgets")
    expected_keys = {
        "postgres_and_wal_bytes",
        "business_data_bytes",
        "ocr_models_bytes",
        "filesystem_and_runtime_bytes",
    }
    _require(set(budgets) == expected_keys, "50 GiB预算字段集合无效")
    _require(budgets["postgres_and_wal_bytes"] == 12 * GIB, "数据库与WAL预算必须为12 GiB")
    _require(budgets["ocr_models_bytes"] == 4 * GIB, "OCR模型预算必须为4 GiB")
    business_bytes = int(budgets["business_data_bytes"])
    _require(0 < business_bytes <= 32 * GIB, "业务文件预算必须大于0且不超过32 GiB")
    data_budget = 12 * GIB + business_bytes + 4 * GIB
    _require(data_budget <= 48 * GIB, "持久化数据预算不得超过48 GiB")
    _require(
        int(budgets["filesystem_and_runtime_bytes"]) == 50 * GIB - data_budget,
        "文件系统与运行余量必须补足50 GiB且至少为2 GiB",
    )
    _require(int(budgets["filesystem_and_runtime_bytes"]) >= 2 * GIB, "运行余量不得低于2 GiB")

    loop_storage = allocation.get("loop_storage")
    _require(isinstance(loop_storage, dict), "资源确认缺少loop_storage")
    expected_loop = {
        "backing_file": BACKING_FILE,
        "backing_file_bytes": 50 * GIB,
        "fully_preallocated": True,
        "sparse_file_forbidden": True,
        "filesystem_type": "ext4",
        "reserved_blocks_percent": 0,
        "mount_point": MOUNT_POINT,
        "mount_options": ["loop", "nodev", "nosuid", "noatime"],
        "autoclear_required": True,
        "systemd_unit_name": UNIT_NAME,
        "systemd_unit_path": UNIT_INSTALL_PATH,
        "requires_mounts_for": "/mnt/data",
        "rollback_documented": True,
    }
    _require(loop_storage == expected_loop, "loop ext4计划与固定边界不一致")

    logging = allocation.get("docker_logging")
    _require(isinstance(logging, dict), "资源确认缺少docker_logging")
    _require(
        logging
        == {
            "storage_scope": "shared_docker_root_outside_uat_loop",
            "driver": "json-file",
            "max_size": "10m",
            "max_file": 3,
            "max_container_count": 8,
            "maximum_bytes": 240 * 1024**2,
        },
        "Docker日志边界必须为8个容器、每个10m×3且位于loop之外",
    )
    return budgets, data_budget


def _validate_mount_unit(path: Path) -> str:
    try:
        raw = path.read_bytes()
        text = raw.decode("utf-8")
    except (OSError, UnicodeDecodeError) as exc:
        raise LoopStorageError(f"无法读取systemd mount模板：{path}") from exc
    _require("# 回滚：" in text, "systemd mount模板缺少明确回滚说明")
    parser = configparser.ConfigParser(interpolation=None, strict=True)
    parser.optionxform = str
    try:
        parser.read_string(text)
    except configparser.Error as exc:
        raise LoopStorageError("systemd mount模板语法无效") from exc
    _require(set(parser.sections()) == {"Unit", "Mount", "Install"}, "mount模板段落集合无效")
    unit = parser["Unit"]
    mount = parser["Mount"]
    install = parser["Install"]
    _require(unit.get("RequiresMountsFor") == "/mnt/data", "mount单元必须依赖/mnt/data")
    _require(unit.get("After") == "mnt-data.mount", "mount单元必须在/mnt/data之后启动")
    _require(unit.get("ConditionPathIsReadWrite") == "/mnt/data", "必须确认/mnt/data可写")
    _require(unit.get("ConditionPathIsRegular") == BACKING_FILE, "后备文件条件无效")
    _require(mount.get("What") == BACKING_FILE, "mount单元后备文件无效")
    _require(mount.get("Where") == MOUNT_POINT, "mount单元挂载点无效")
    _require(mount.get("Type") == "ext4", "mount单元文件系统必须为ext4")
    options = {item.strip() for item in mount.get("Options", "").split(",") if item.strip()}
    _require(options == REQUIRED_MOUNT_OPTIONS, "mount参数必须精确为loop,nodev,nosuid,noatime")
    _require(mount.get("TimeoutSec") == "120", "mount超时必须为120秒")
    _require(install.get("WantedBy") == "multi-user.target", "mount单元必须持久启用")
    return hashlib.sha256(raw).hexdigest()


def validate_loop_storage_plan(allocation_path: Path, mount_unit_path: Path) -> LoopStorageResult:
    allocation, allocation_sha256 = _load_json(allocation_path, "资源确认")
    budgets, _ = _storage_contract(allocation)
    unit_sha256 = _validate_mount_unit(mount_unit_path)
    return LoopStorageResult(
        mode="plan",
        allocation_sha256=allocation_sha256,
        unit_sha256=unit_sha256,
        evidence_sha256=None,
        business_data_bytes=int(budgets["business_data_bytes"]),
        usable_bytes=None,
    )


def validate_loop_storage_evidence(
    allocation_path: Path,
    mount_unit_path: Path,
    evidence_path: Path,
    *,
    ci_fixture: bool = False,
) -> LoopStorageResult:
    plan = validate_loop_storage_plan(allocation_path, mount_unit_path)
    allocation, _ = _load_json(allocation_path, "资源确认")
    _, data_budget = _storage_contract(allocation)
    evidence, evidence_sha256 = _load_json(evidence_path, "loop存储证据")
    _require(evidence.get("schema_version") == "1.0", "loop存储证据版本无效")
    captured_at = str(evidence.get("captured_at", ""))
    _require(bool(captured_at), "loop存储证据缺少采集时间")
    if not ci_fixture:
        _require(not _has_placeholder(captured_at), "loop存储采集时间仍是占位值")

    backing = evidence.get("backing_file")
    _require(isinstance(backing, dict), "loop存储证据缺少backing_file")
    _require(backing.get("path") == BACKING_FILE, "loop后备文件路径无效")
    _require(backing.get("size_bytes") == 50 * GIB, "loop后备文件必须精确为50 GiB")
    _require(
        int(backing.get("allocated_bytes", 0)) >= 50 * GIB and backing.get("sparse") is False,
        "loop后备文件必须完整预分配且禁止稀疏文件",
    )
    _require(str(backing.get("mode")) == "0600", "loop后备文件权限必须为0600")

    filesystem = evidence.get("filesystem")
    _require(isinstance(filesystem, dict), "loop存储证据缺少filesystem")
    _require(filesystem.get("type") == "ext4", "loop文件系统必须为ext4")
    _require(filesystem.get("label") == "smartscan-uat", "loop文件系统标签无效")
    _require(filesystem.get("reserved_blocks_percent") == 0, "ext4 reserved block比例必须为0")
    usable_bytes = int(filesystem.get("usable_bytes", 0))
    _require(usable_bytes >= data_budget, "实际可用空间不足，必须降低业务文件预算")

    mount = evidence.get("mount")
    _require(isinstance(mount, dict) and mount.get("active") is True, "loop挂载尚未激活")
    _require(
        re.fullmatch(r"/dev/loop[0-9]+", str(mount.get("source", ""))) is not None,
        "挂载源不是loop设备",
    )
    _require(mount.get("target") == MOUNT_POINT, "实际挂载点无效")
    _require(mount.get("type") == "ext4", "实际挂载类型必须为ext4")
    mount_options = set(mount.get("options", []))
    _require(
        REQUIRED_RUNTIME_MOUNT_OPTIONS <= mount_options,
        "实际挂载缺少nodev,nosuid,noatime；loop由设备来源和单元配置交叉验证",
    )

    loop = evidence.get("loop")
    _require(isinstance(loop, dict), "loop存储证据缺少loop设备状态")
    _require(loop.get("backing_file") == BACKING_FILE, "loop设备绑定了错误后备文件")
    _require(loop.get("autoclear") is True, "loop设备必须启用autoclear")

    systemd_unit = evidence.get("systemd_unit")
    _require(isinstance(systemd_unit, dict), "loop存储证据缺少systemd_unit")
    _require(systemd_unit.get("name") == UNIT_NAME, "systemd mount单元名称无效")
    _require(systemd_unit.get("path") == UNIT_INSTALL_PATH, "systemd mount单元路径无效")
    _require(str(systemd_unit.get("mode")) == "0644", "systemd mount单元权限必须为0644")
    _require(
        systemd_unit.get("enabled") is True and systemd_unit.get("active") is True,
        "systemd mount单元必须已启用且激活",
    )
    _require(systemd_unit.get("requires_mounts_for") == "/mnt/data", "systemd单元缺少/mnt/data依赖")
    rollback_record = str(systemd_unit.get("rollback_record", ""))
    _require(bool(rollback_record), "systemd单元缺少回滚记录")
    if not ci_fixture:
        _require(not _has_placeholder(rollback_record), "systemd回滚记录仍是占位值")
    _require(evidence.get("contains_sensitive_data") is False, "loop证据不得包含敏感数据")

    return LoopStorageResult(
        mode="created",
        allocation_sha256=plan.allocation_sha256,
        unit_sha256=plan.unit_sha256,
        evidence_sha256=evidence_sha256,
        business_data_bytes=plan.business_data_bytes,
        usable_bytes=usable_bytes,
    )


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--allocation", type=Path, required=True)
    parser.add_argument("--mount-unit", type=Path, required=True)
    parser.add_argument("--evidence", type=Path)
    parser.add_argument("--ci-fixture", action="store_true")
    arguments = parser.parse_args()
    try:
        if arguments.evidence:
            result = validate_loop_storage_evidence(
                arguments.allocation,
                arguments.mount_unit,
                arguments.evidence,
                ci_fixture=arguments.ci_fixture,
            )
        else:
            result = validate_loop_storage_plan(arguments.allocation, arguments.mount_unit)
    except LoopStorageError as exc:
        print(json.dumps({"status": "failed", "error": str(exc)}, ensure_ascii=False))
        return 1
    print(json.dumps(result.safe_summary(), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
