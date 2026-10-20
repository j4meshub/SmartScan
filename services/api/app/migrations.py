from __future__ import annotations

import argparse
from pathlib import Path

from alembic import command
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.script import ScriptDirectory
from sqlalchemy import create_engine, inspect

from . import models as _models  # noqa: F401  # 注册全部 SQLAlchemy 模型
from .config import get_settings
from .database import Base

BASELINE_REVISION = "20261020_0001"
PROJECT_ROOT = Path(__file__).resolve().parents[3]


def alembic_config(database_url: str | None = None) -> Config:
    config = Config(str(PROJECT_ROOT / "alembic.ini"))
    config.set_main_option("script_location", str(PROJECT_ROOT / "migrations"))
    config.set_main_option("sqlalchemy.url", database_url or get_settings().database_url)
    return config


def _schema_tables(database_url: str) -> set[str]:
    engine = create_engine(database_url)
    try:
        return set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()


def _validate_legacy_baseline(database_url: str) -> None:
    expected_tables = set(Base.metadata.tables)
    actual_tables = _schema_tables(database_url)
    if actual_tables != expected_tables:
        missing = sorted(expected_tables - actual_tables)
        unexpected = sorted(actual_tables - expected_tables)
        raise RuntimeError(
            f"无法自动接管旧数据库基线：缺少表 {missing or '无'}，额外表 {unexpected or '无'}。"
        )

    engine = create_engine(database_url)
    try:
        schema = inspect(engine)
        for table_name, table in Base.metadata.tables.items():
            expected_columns = set(table.columns.keys())
            actual_columns = {column["name"] for column in schema.get_columns(table_name)}
            if actual_columns != expected_columns:
                missing = sorted(expected_columns - actual_columns)
                unexpected = sorted(actual_columns - expected_columns)
                raise RuntimeError(
                    f"无法自动接管旧数据库基线：表 {table_name} "
                    f"缺少列 {missing or '无'}，额外列 {unexpected or '无'}。"
                )
    finally:
        engine.dispose()


def upgrade_database(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    config = alembic_config(url)
    tables = _schema_tables(url)
    if tables and "alembic_version" not in set(_all_tables(url)):
        _validate_legacy_baseline(url)
        command.stamp(config, BASELINE_REVISION)
    command.upgrade(config, "head")


def _all_tables(database_url: str) -> list[str]:
    engine = create_engine(database_url)
    try:
        return inspect(engine).get_table_names()
    finally:
        engine.dispose()


def current_revision(database_url: str | None = None) -> str | None:
    url = database_url or get_settings().database_url
    engine = create_engine(url)
    try:
        with engine.connect() as connection:
            return MigrationContext.configure(connection).get_current_revision()
    finally:
        engine.dispose()


def head_revision(database_url: str | None = None) -> str:
    return ScriptDirectory.from_config(alembic_config(database_url)).get_current_head()


def ensure_database_current(database_url: str | None = None) -> None:
    url = database_url or get_settings().database_url
    current = current_revision(url)
    head = head_revision(url)
    if current != head:
        raise RuntimeError(
            "数据库迁移版本不匹配："
            f"当前版本为 {current or '未初始化'}，目标版本为 {head}。"
            "请先执行 python -m services.api.app.migrations upgrade。"
        )


def check_database_drift(database_url: str | None = None) -> None:
    command.check(alembic_config(database_url))


def main() -> None:
    parser = argparse.ArgumentParser(description="SmartScan 数据库迁移入口")
    parser.add_argument("action", choices=("upgrade", "check", "current", "drift"))
    args = parser.parse_args()
    if args.action == "upgrade":
        upgrade_database()
    elif args.action == "check":
        ensure_database_current()
    elif args.action == "drift":
        check_database_drift()
    else:
        print(current_revision() or "未初始化")


if __name__ == "__main__":
    main()
