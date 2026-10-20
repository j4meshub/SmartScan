from __future__ import annotations

import hashlib
import os
from collections.abc import Iterator
from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, select, text
from sqlalchemy.engine import make_url
from sqlalchemy.orm import Session

from services.api.app.account_deletion import process_account_deletion
from services.api.app.config import Settings
from services.api.app.migrations import (
    BASELINE_REVISION,
    alembic_config,
    current_revision,
    head_revision,
    upgrade_database,
)
from services.api.app.models import (
    AccountDeletionRequest,
    AccountDeletionStatus,
    PhoneEncryptionStatus,
    PhoneReuseQuarantine,
    RefreshToken,
    SessionToken,
    User,
    UserIdentity,
    VerifiedPhone,
)
from services.api.app.session_service import SessionFlowError, rotate_refresh_token

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


def test_postgresql_concurrent_account_deletion_is_idempotent(tmp_path: Path) -> None:
    url = isolated_postgres_url()
    upgrade_database(url)
    engine = create_engine(url)
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(
            id="deletion-race-user",
            username="deletion-race",
            password_hash="hash",
            phone_hmac="7" * 64,
            phone_masked="+86******0007",
            status="deleting",
        )
        session.add(user)
        session.flush()
        session.add(
            VerifiedPhone(
                user_id=user.id,
                phone_hmac="7" * 64,
                hmac_key_id="legacy-v1",
                phone_masked="+86******0007",
                encryption_status=PhoneEncryptionStatus.unavailable,
                verification_source="legacy",
            )
        )
        session.add(
            AccountDeletionRequest(
                id="deletion-race-request",
                user_id=user.id,
                requested_by_user_id=user.id,
                request_source="self_service",
                status=AccountDeletionStatus.pending,
                requested_at=now - timedelta(days=8),
                execute_after=now - timedelta(days=1),
            )
        )
        session.commit()

    settings = Settings(database_url=url, storage_root=tmp_path)

    def delete_once() -> str:
        with Session(engine) as session:
            result = process_account_deletion(
                session,
                "deletion-race-request",
                now=now,
                settings=settings,
            )
            return result.status.value

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: delete_once(), range(2)))

    assert outcomes == ["completed", "completed"]
    with Session(engine) as session:
        deletion = session.get(AccountDeletionRequest, "deletion-race-request")
        user = session.get(User, "deletion-race-user")
        quarantines = session.scalars(select(PhoneReuseQuarantine)).all()
        assert deletion is not None and deletion.status == AccountDeletionStatus.completed
        assert user is not None and user.status == "deleted"
        assert len(quarantines) == 1
    engine.dispose()


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
                    "('users_protect_super_admin', 'audit_logs_no_mutation', "
                    "'account_merge_audits_no_mutation')"
                )
            )
    finally:
        engine.dispose()
    assert index_count == 1
    assert trigger_count == 3


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
    assert phone.hmac_key_id == "legacy-v1"
    assert phone.encryption_status == PhoneEncryptionStatus.unavailable
    assert phone.phone_ciphertext is None
    assert current_revision(url) == head_revision(url)
    assert_postgresql_guards_installed()


def test_postgresql_concurrent_refresh_detects_replay_and_revokes_family() -> None:
    url = isolated_postgres_url()
    upgrade_database(url)
    engine = create_engine(url)
    raw_refresh = "postgres-concurrent-refresh-" + "x" * 64
    now = datetime.now(UTC)
    with Session(engine) as session:
        user = User(
            id="refresh-race-user",
            username="refresh-race",
            password_hash="hash",
            phone_hmac="9" * 64,
            phone_masked="+86******0009",
        )
        session.add(user)
        session.flush()
        device_session = SessionToken(
            id="refresh-race-session",
            user_id=user.id,
            token_hash="8" * 64,
            device_id="postgres-race-device",
            device_name="PostgreSQL 并发设备",
            platform="test",
            expires_at=now + timedelta(minutes=15),
            last_seen_at=now,
        )
        session.add(device_session)
        session.flush()
        session.add(
            RefreshToken(
                session_id=device_session.id,
                token_hash=hashlib.sha256(raw_refresh.encode()).hexdigest(),
                expires_at=now + timedelta(days=1),
            )
        )
        session.commit()

    def rotate_once() -> str:
        with Session(engine) as session:
            try:
                rotate_refresh_token(session, raw_refresh)
            except SessionFlowError as exc:
                return exc.code
            return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        outcomes = sorted(executor.map(lambda _: rotate_once(), range(2)))

    assert outcomes == ["refresh_token_replayed", "success"]
    with Session(engine) as session:
        device_session = session.get(SessionToken, "refresh-race-session")
        refresh_rows = session.scalars(
            select(RefreshToken).where(RefreshToken.session_id == "refresh-race-session")
        ).all()
        assert device_session is not None and device_session.revoked_at is not None
        assert len(refresh_rows) == 2
        assert all(item.revoked_at is not None for item in refresh_rows)
    engine.dispose()
