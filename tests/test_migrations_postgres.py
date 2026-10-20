from __future__ import annotations

import os
from collections.abc import Iterator

import pytest
from alembic import command
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from services.api.app.migrations import (
    BASELINE_REVISION,
    alembic_config,
    current_revision,
    head_revision,
    upgrade_database,
)
from services.api.app.models import User, UserIdentity, VerifiedPhone

POSTGRES_URL = os.getenv("SMARTSCAN_TEST_POSTGRES_URL")
pytestmark = pytest.mark.skipif(not POSTGRES_URL, reason="未配置隔离 PostgreSQL 测试库")


def isolated_postgres_url() -> str:
    assert POSTGRES_URL is not None
    database_name = make_url(POSTGRES_URL).database or ""
    if not database_name.endswith("_test"):
        pytest.fail("PostgreSQL 迁移测试只允许操作名称以 _test 结尾的隔离数据库")
    return POSTGRES_URL


@pytest.fixture(autouse=True)
def reset_postgres_schema() -> Iterator[None]:
    engine = create_engine(isolated_postgres_url())
    with engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    engine.dispose()
    yield
    cleanup_engine = create_engine(isolated_postgres_url())
    with cleanup_engine.begin() as connection:
        connection.execute(text("DROP SCHEMA public CASCADE"))
        connection.execute(text("CREATE SCHEMA public"))
    cleanup_engine.dispose()


def assert_postgresql_guards_installed() -> None:
    engine = create_engine(isolated_postgres_url())
    try:
        with engine.connect() as connection:
            index_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_indexes "
                    "WHERE schemaname = 'public' AND indexname = 'users_one_super_admin'"
                )
            )
            trigger_count = connection.scalar(
                text(
                    "SELECT count(*) FROM pg_trigger "
                    "WHERE NOT tgisinternal AND tgname IN "
                    "('users_protect_super_admin', 'audit_logs_no_mutation')"
                )
            )
    finally:
        engine.dispose()
    assert index_count == 1
    assert trigger_count == 2


def test_postgresql_empty_database_upgrades_with_guards() -> None:
    url = isolated_postgres_url()

    upgrade_database(url)

    assert current_revision(url) == head_revision(url)
    assert_postgresql_guards_installed()


def test_postgresql_legacy_baseline_is_adopted_and_guarded() -> None:
    url = isolated_postgres_url()
    command.upgrade(alembic_config(url), BASELINE_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    with Session(engine) as session:
        session.add(
            User(
                id="postgres-legacy-user",
                username="postgres-legacy",
                password_hash="hash",
                phone_hmac="b" * 64,
                phone_masked="+86******0001",
            )
        )
        session.commit()
    engine.dispose()

    upgrade_database(url)

    migrated_engine = create_engine(url)
    try:
        with Session(migrated_engine) as session:
            username = session.scalar(
                select(User.username).where(User.id == "postgres-legacy-user")
            )
            identity = session.scalar(
                select(UserIdentity).where(UserIdentity.user_id == "postgres-legacy-user")
            )
            phone = session.scalar(
                select(VerifiedPhone).where(VerifiedPhone.user_id == "postgres-legacy-user")
            )
    finally:
        migrated_engine.dispose()
    assert username == "postgres-legacy"
    assert identity is not None and identity.credential_hash == "hash"
    assert phone is not None and phone.verification_source == "legacy"
    assert current_revision(url) == head_revision(url)
    assert_postgresql_guards_installed()
