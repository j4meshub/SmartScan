"""记录、比较并生成 SmartScan BBR 回滚配置；本工具不修改内核参数。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

SCHEMA = "smartscan-bbr-snapshot-v1"
TOKEN = re.compile(r"^[a-z0-9_.+-]{1,64}$")


class BbrBaselineError(ValueError):
    """BBR 基线或对照证据无效。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise BbrBaselineError(message)


def _read_one(path: Path, label: str) -> str:
    try:
        value = path.read_text(encoding="utf-8").strip()
    except OSError as exc:
        raise BbrBaselineError(f"无法读取 {label}：{path}") from exc
    _require(bool(value) and "\n" not in value and "\r" not in value, f"{label} 值无效")
    return value


def _safe_token(value: str, label: str) -> str:
    normalized = value.casefold()
    _require(TOKEN.fullmatch(normalized) is not None, f"{label} 包含不安全字符")
    return normalized


def capture_snapshot(
    *,
    proc_sys_root: Path = Path("/proc/sys"),
    modules_path: Path = Path("/proc/modules"),
    machine_id_path: Path = Path("/etc/machine-id"),
    now: datetime | None = None,
) -> dict[str, Any]:
    available_raw = _read_one(
        proc_sys_root / "net/ipv4/tcp_available_congestion_control",
        "可用拥塞控制列表",
    )
    available = [_safe_token(item, "可用拥塞控制算法") for item in available_raw.split()]
    _require(bool(available) and len(available) == len(set(available)), "可用拥塞控制列表无效")
    active = _safe_token(
        _read_one(proc_sys_root / "net/ipv4/tcp_congestion_control", "当前拥塞控制"),
        "当前拥塞控制",
    )
    qdisc = _safe_token(
        _read_one(proc_sys_root / "net/core/default_qdisc", "默认队列规则"),
        "默认队列规则",
    )
    kernel = _safe_token(
        _read_one(proc_sys_root / "kernel/osrelease", "内核版本"),
        "内核版本",
    )
    machine_id = _read_one(machine_id_path, "主机 machine-id")
    _require(re.fullmatch(r"[0-9a-fA-F]{32}", machine_id) is not None, "主机 machine-id 格式无效")
    host_fingerprint = hashlib.sha256(f"smartscan-bbr:{machine_id.casefold()}".encode()).hexdigest()
    try:
        modules = modules_path.read_text(encoding="utf-8").splitlines()
    except OSError:
        modules = []
    module_loaded = any(line.split(maxsplit=1)[0] == "tcp_bbr" for line in modules if line.strip())
    captured_at = (now or datetime.now(UTC)).astimezone(UTC)
    return {
        "schema": SCHEMA,
        "captured_at": captured_at.isoformat(),
        "kernel_release": kernel,
        "host_fingerprint_sha256": host_fingerprint,
        "available_congestion_controls": available,
        "active_congestion_control": active,
        "default_qdisc": qdisc,
        "tcp_bbr_module_loaded": module_loaded,
        "source": "linux_procfs",
    }


def validate_snapshot(snapshot: object) -> dict[str, Any]:
    _require(isinstance(snapshot, dict), "BBR 快照根节点必须是对象")
    required = {
        "schema",
        "captured_at",
        "kernel_release",
        "host_fingerprint_sha256",
        "available_congestion_controls",
        "active_congestion_control",
        "default_qdisc",
        "tcp_bbr_module_loaded",
        "source",
    }
    _require(set(snapshot) == required, "BBR 快照字段集合不匹配")
    _require(snapshot["schema"] == SCHEMA, "BBR 快照版本不支持")
    try:
        captured_at = datetime.fromisoformat(str(snapshot["captured_at"]))
    except ValueError as exc:
        raise BbrBaselineError("BBR 快照时间无效") from exc
    _require(captured_at.tzinfo is not None, "BBR 快照时间必须包含时区")
    kernel = _safe_token(str(snapshot["kernel_release"]), "内核版本")
    host_fingerprint = str(snapshot["host_fingerprint_sha256"])
    _require(
        re.fullmatch(r"[0-9a-f]{64}", host_fingerprint) is not None,
        "主机指纹必须是 SHA-256",
    )
    active = _safe_token(str(snapshot["active_congestion_control"]), "当前拥塞控制")
    qdisc = _safe_token(str(snapshot["default_qdisc"]), "默认队列规则")
    available_raw = snapshot["available_congestion_controls"]
    _require(isinstance(available_raw, list) and available_raw, "可用拥塞控制列表无效")
    available = [_safe_token(str(item), "可用拥塞控制算法") for item in available_raw]
    _require(len(available) == len(set(available)), "可用拥塞控制列表包含重复项")
    _require(active in available, "当前拥塞控制不在可用列表中")
    _require(isinstance(snapshot["tcp_bbr_module_loaded"], bool), "BBR 模块状态必须是布尔值")
    _require(snapshot["source"] == "linux_procfs", "BBR 快照来源不受支持")
    return {
        "schema": SCHEMA,
        "captured_at": captured_at.astimezone(UTC).isoformat(),
        "kernel_release": kernel,
        "host_fingerprint_sha256": host_fingerprint,
        "available_congestion_controls": available,
        "active_congestion_control": active,
        "default_qdisc": qdisc,
        "tcp_bbr_module_loaded": snapshot["tcp_bbr_module_loaded"],
        "source": "linux_procfs",
    }


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        document = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BbrBaselineError(f"无法读取 BBR 快照：{path}") from exc
    return validate_snapshot(document)


def evaluate_transition(before: object, after: object) -> dict[str, Any]:
    before = validate_snapshot(before)
    after = validate_snapshot(after)
    checks = {
        "same_host": before["host_fingerprint_sha256"] == after["host_fingerprint_sha256"],
        "same_kernel": before["kernel_release"] == after["kernel_release"],
        "after_is_later": after["captured_at"] > before["captured_at"],
        "bbr_available": "bbr" in after["available_congestion_controls"],
        "bbr_active": after["active_congestion_control"] == "bbr",
        "fq_active": after["default_qdisc"] == "fq",
    }
    return {
        "schema": "smartscan-bbr-transition-v1",
        "before_captured_at": before["captured_at"],
        "after_captured_at": after["captured_at"],
        "kernel_release": after["kernel_release"],
        "checks": checks,
        "ready_for_controlled_network_comparison": all(checks.values()),
        "module_loaded_is_supplementary": after["tcp_bbr_module_loaded"],
        "core_network_gate_complete": False,
    }


def render_rollback(snapshot: object) -> str:
    normalized = validate_snapshot(snapshot)
    return (
        "# 由变更前 SmartScan BBR 快照生成；人工复核后安装。\n"
        f"net.core.default_qdisc={normalized['default_qdisc']}\n"
        "net.ipv4.tcp_congestion_control="
        f"{normalized['active_congestion_control']}\n"
    )


def write_new_json(path: Path, document: object, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(document, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
    except FileExistsError as exc:
        raise BbrBaselineError(f"拒绝覆盖已有证据：{path}") from exc
    if os.name != "nt":
        path.chmod(mode)


def write_new_text(path: Path, content: str, *, mode: int = 0o600) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
    except FileExistsError as exc:
        raise BbrBaselineError(f"拒绝覆盖已有回滚配置：{path}") from exc
    if os.name != "nt":
        path.chmod(mode)


def main() -> int:
    parser = argparse.ArgumentParser(description="记录、比较并生成 SmartScan BBR 回滚配置")
    subparsers = parser.add_subparsers(dest="command", required=True)

    capture = subparsers.add_parser("capture", help="从 Linux procfs 记录只读快照")
    capture.add_argument("--output", required=True, type=Path)

    evaluate = subparsers.add_parser("evaluate", help="比较启用前后快照")
    evaluate.add_argument("--before", required=True, type=Path)
    evaluate.add_argument("--after", required=True, type=Path)
    evaluate.add_argument("--output", required=True, type=Path)

    rollback = subparsers.add_parser("render-rollback", help="从启用前快照生成回滚参数")
    rollback.add_argument("--snapshot", required=True, type=Path)
    rollback.add_argument("--output", required=True, type=Path)
    args = parser.parse_args()

    if args.command == "capture":
        write_new_json(args.output, capture_snapshot())
    elif args.command == "evaluate":
        write_new_json(
            args.output,
            evaluate_transition(load_snapshot(args.before), load_snapshot(args.after)),
        )
    else:
        write_new_text(args.output, render_rollback(load_snapshot(args.snapshot)))
    print(f"BBR {args.command} 证据已生成：{args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
