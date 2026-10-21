"""在隔离恢复容器中验证数据库、所有权和持久文件，不输出用户数据。"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
from typing import Any

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect, text

from tools.backup_evidence import atomic_write_json

PROJECT_ROOT = Path(__file__).resolve().parents[3]
COUNT_TABLES = (
    "users",
    "user_identities",
    "verified_phones",
    "scan_projects",
    "scan_pages",
    "page_results",
    "scan_exports",
    "export_artifacts",
    "processing_jobs",
    "audit_logs",
)


class RestoreVerificationError(RuntimeError):
    """恢复内容没有通过一致性检查。"""


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise RestoreVerificationError(message)


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _safe_file(root: Path, relative: str, owner: str) -> Path:
    pure = PurePosixPath(relative)
    _require(not pure.is_absolute() and ".." not in pure.parts, "文件路径越界")
    _require(len(pure.parts) >= 3 and pure.parts[:2] == ("users", owner), "文件所有权路径不匹配")
    candidate = root.joinpath(*pure.parts)
    _require(candidate.is_file() and not candidate.is_symlink(), "持久文件缺失或为符号链接")
    try:
        candidate.resolve(strict=True).relative_to(root.resolve(strict=True))
    except ValueError as exc:
        raise RestoreVerificationError("持久文件解析后越界") from exc
    return candidate


def verify_restore(database_url: str, storage_root: Path) -> dict[str, Any]:
    _require(storage_root.is_dir() and not storage_root.is_symlink(), "恢复文件根目录无效")
    engine = create_engine(database_url, pool_pre_ping=True)
    try:
        schema = inspect(engine)
        tables = set(schema.get_table_names())
        _require(set(COUNT_TABLES) <= tables, "恢复数据库缺少关键表")
        alembic = Config(str(PROJECT_ROOT / "alembic.ini"))
        alembic.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
        expected_revision = ScriptDirectory.from_config(alembic).get_current_head()
        counts: dict[str, int] = {}
        with engine.connect() as connection:
            revision = connection.execute(
                text("SELECT version_num FROM alembic_version")
            ).scalar_one()
            _require(revision == expected_revision, "恢复数据库迁移版本不是当前头")
            for table in COUNT_TABLES:
                counts[table] = int(
                    connection.execute(text(f'SELECT count(*) FROM "{table}"')).scalar_one()
                )
            super_admin_count = int(
                connection.execute(
                    text("SELECT count(*) FROM users WHERE role='super_admin'")
                ).scalar_one()
            )
            _require(super_admin_count == 1, "恢复数据库必须且只能包含一个超级管理员")

            mismatch_queries = {
                "page_project_owner": """
                    SELECT count(*) FROM scan_pages p JOIN scan_projects r ON r.id=p.project_id
                    WHERE p.owner_user_id<>r.owner_user_id
                """,
                "result_page_owner": """
                    SELECT count(*) FROM page_results r JOIN scan_pages p ON p.id=r.page_id
                    WHERE r.owner_user_id<>p.owner_user_id
                """,
                "export_project_owner": """
                    SELECT count(*) FROM scan_exports e JOIN scan_projects p ON p.id=e.project_id
                    WHERE e.owner_user_id<>p.owner_user_id
                """,
                "artifact_export_owner": """
                    SELECT count(*) FROM export_artifacts a JOIN scan_exports e ON e.id=a.export_id
                    WHERE a.owner_user_id<>e.owner_user_id
                """,
                "identity_user": """
                    SELECT count(*) FROM user_identities i LEFT JOIN users u ON u.id=i.user_id
                    WHERE u.id IS NULL
                """,
                "phone_user": """
                    SELECT count(*) FROM verified_phones p LEFT JOIN users u ON u.id=p.user_id
                    WHERE u.id IS NULL
                """,
            }
            for label, query in mismatch_queries.items():
                _require(
                    int(connection.execute(text(query)).scalar_one()) == 0,
                    f"所有权一致性失败：{label}",
                )

            references: list[tuple[str, str, str | None, int | None]] = []
            references.extend(
                (row.original_path, row.owner_user_id, row.sha256, row.size_bytes)
                for row in connection.execute(
                    text("SELECT original_path, owner_user_id, sha256, size_bytes FROM scan_pages")
                )
            )
            references.extend(
                (row.processed_path, row.owner_user_id, None, None)
                for row in connection.execute(
                    text(
                        "SELECT processed_path, owner_user_id FROM scan_pages "
                        "WHERE processed_path IS NOT NULL"
                    )
                )
            )
            references.extend(
                (row.book_logical_source_path, row.owner_user_id, None, None)
                for row in connection.execute(
                    text(
                        "SELECT book_logical_source_path, owner_user_id FROM scan_pages "
                        "WHERE book_logical_source_path IS NOT NULL"
                    )
                )
            )
            references.extend(
                (row.file_path, row.owner_user_id, row.sha256, row.size_bytes)
                for row in connection.execute(
                    text("SELECT file_path, owner_user_id, sha256, size_bytes FROM page_results")
                )
            )
            references.extend(
                (row.relative_path, row.owner_user_id, row.sha256, row.size_bytes)
                for row in connection.execute(
                    text(
                        "SELECT c.relative_path, u.owner_user_id, c.sha256, c.size_bytes "
                        "FROM upload_chunks c JOIN upload_sessions u ON u.id=c.upload_id"
                    )
                )
            )
            references.extend(
                (row.file_path, row.owner_user_id, row.sha256, row.size_bytes)
                for row in connection.execute(
                    text(
                        "SELECT file_path, owner_user_id, sha256, size_bytes FROM export_artifacts"
                    )
                )
            )
        total_bytes = 0
        for relative, owner, expected_hash, expected_size in references:
            path = _safe_file(storage_root, relative, owner)
            size = path.stat().st_size
            _require(expected_size is None or size == expected_size, "持久文件大小不一致")
            _require(expected_hash is None or _hash(path) == expected_hash, "持久文件哈希不一致")
            total_bytes += size
        return {
            "schema_version": 1,
            "status": "success",
            "database_revision": expected_revision,
            "table_counts": counts,
            "verified_file_count": len(references),
            "verified_file_bytes": total_bytes,
            "ownership_checks": 6,
            "super_admin_count": super_admin_count,
            "secrets_included": False,
        }
    finally:
        engine.dispose()


def main() -> int:
    parser = argparse.ArgumentParser(description="验证 SmartScan 隔离恢复内容")
    parser.add_argument("--output", type=Path, help="可选的 0600 证据文件；默认只输出安全 JSON")
    args = parser.parse_args()
    database_url = os.environ.get("SMARTSCAN_DATABASE_URL", "")
    storage_root = Path(os.environ.get("SMARTSCAN_STORAGE_ROOT", ""))
    _require(bool(database_url), "缺少恢复数据库 URL")
    result = verify_restore(database_url, storage_root)
    if args.output:
        atomic_write_json(args.output, result)
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
