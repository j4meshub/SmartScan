"""OPS-004 备份与恢复的无敏感信息证据模型。"""

from __future__ import annotations

import json
import os
import re
import tempfile
from pathlib import Path
from typing import Any

RUN_ID = re.compile(r"^\d{8}T\d{6}Z-[a-f0-9]{12}$")
SNAPSHOT_ID = re.compile(r"^[a-f0-9]{64}$")
GIT_COMMIT = re.compile(r"^[a-f0-9]{40}$")
KINDS = ("database", "files", "wal")


class EvidenceError(ValueError):
    """证据内容不完整、被篡改或包含越界值。"""


def atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """以 0600 原子写入 JSON，避免保留半份成功证据。"""

    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    temporary_path = Path(temporary)
    try:
        os.chmod(temporary_path, 0o600)
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary_path, path)
    finally:
        temporary_path.unlink(missing_ok=True)


def load_successful_backup(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EvidenceError("无法读取备份证据") from exc
    if not isinstance(payload, dict) or payload.get("schema_version") != 1:
        raise EvidenceError("备份证据版本无效")
    if payload.get("status") != "success" or not RUN_ID.fullmatch(str(payload.get("run_id", ""))):
        raise EvidenceError("只允许使用成功且格式有效的备份证据")
    if not GIT_COMMIT.fullmatch(str(payload.get("git_commit", ""))):
        raise EvidenceError("备份证据 Git 提交无效")
    snapshots = payload.get("snapshots")
    if not isinstance(snapshots, dict) or set(snapshots) != set(KINDS):
        raise EvidenceError("备份证据必须包含数据库、文件和 WAL 快照")
    if not all(SNAPSHOT_ID.fullmatch(str(value)) for value in snapshots.values()):
        raise EvidenceError("备份快照 ID 无效")
    return payload
