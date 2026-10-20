from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from services.api.app.database import Base
from services.api.app.migrations import (
    alembic_config,
    check_database_drift,
    current_revision,
    ensure_database_current,
    head_revision,
    upgrade_database,
)
from services.api.app.models import User


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def test_empty_database_upgrades_to_head(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "empty.db")

    upgrade_database(url)

    engine = create_engine(url)
    try:
        tables = set(inspect(engine).get_table_names())
    finally:
        engine.dispose()
    assert set(Base.metadata.tables).issubset(tables)
    assert "alembic_version" in tables
    assert current_revision(url) == head_revision(url)
    ensure_database_current(url)
    check_database_drift(url)


def test_legacy_create_all_database_is_adopted_without_data_loss(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "legacy.db")
    engine = create_engine(url)
    Base.metadata.create_all(engine)
    with Session(engine) as session:
        session.add(
            User(
                id="legacy-user",
                username="legacy",
                password_hash="hash",
                phone_hmac="a" * 64,
                phone_masked="+86******0000",
            )
        )
        session.commit()
    engine.dispose()

    upgrade_database(url)

    migrated_engine = create_engine(url)
    try:
        with Session(migrated_engine) as session:
            assert session.scalar(select(User.username).where(User.id == "legacy-user")) == "legacy"
    finally:
        migrated_engine.dispose()
    assert current_revision(url) == head_revision(url)


def test_incomplete_legacy_database_is_rejected(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "incomplete.db")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("CREATE TABLE users (id VARCHAR(36) PRIMARY KEY)"))
    engine.dispose()

    with pytest.raises(RuntimeError, match="无法自动接管旧数据库基线"):
        upgrade_database(url)


def test_outdated_database_is_rejected_by_runtime_check(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "outdated.db")
    upgrade_database(url)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("UPDATE alembic_version SET version_num = 'outdated'"))
    engine.dispose()

    with pytest.raises(RuntimeError, match="数据库迁移版本不匹配"):
        ensure_database_current(url)


def test_initial_migration_can_downgrade_and_upgrade_again(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "rollback.db")
    upgrade_database(url)

    command.downgrade(alembic_config(url), "base")

    engine = create_engine(url)
    try:
        remaining_tables = set(inspect(engine).get_table_names()) - {"alembic_version"}
    finally:
        engine.dispose()
    assert remaining_tables == set()

    upgrade_database(url)
    assert current_revision(url) == head_revision(url)
