from __future__ import annotations

from pathlib import Path

import pytest
from alembic import command
from sqlalchemy import create_engine, inspect, select, text
from sqlalchemy.orm import Session

from services.api.app.database import Base
from services.api.app.migrations import (
    BASELINE_REVISION,
    alembic_config,
    check_database_drift,
    current_revision,
    ensure_database_current,
    head_revision,
    upgrade_database,
)
from services.api.app.models import PhoneEncryptionStatus, User, UserIdentity, VerifiedPhone


def sqlite_url(path: Path) -> str:
    return f"sqlite:///{path.as_posix()}"


def create_unversioned_baseline(url: str) -> None:
    command.upgrade(alembic_config(url), BASELINE_REVISION)
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("DROP TABLE alembic_version"))
    engine.dispose()


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
    create_unversioned_baseline(url)
    engine = create_engine(url)
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
            identity = session.scalar(
                select(UserIdentity).where(UserIdentity.user_id == "legacy-user")
            )
            phone = session.scalar(
                select(VerifiedPhone).where(VerifiedPhone.user_id == "legacy-user")
            )
            assert identity is not None
            assert identity.provider == "local"
            assert identity.provider_subject == "legacy"
            assert identity.credential_hash == "hash"
            assert phone is not None
            assert phone.phone_hmac == "a" * 64
            assert phone.verification_source == "legacy"
            assert phone.hmac_key_id == "legacy-v1"
            assert phone.encryption_status == PhoneEncryptionStatus.unavailable
            assert phone.phone_ciphertext is None
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


def test_legacy_identity_mismatch_is_rejected_instead_of_guessed(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "identity-mismatch.db")
    create_unversioned_baseline(url)
    engine = create_engine(url)
    with Session(engine) as session:
        session.add(
            User(
                id="mismatch-user",
                username="expected-name",
                password_hash="hash",
                phone_hmac="c" * 64,
                phone_masked="+86******0002",
            )
        )
        session.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO user_identities "
                "(id, user_id, provider, provider_subject, verified_at, last_login_at) "
                "VALUES ('mismatch-identity', 'mismatch-user', 'local', "
                "'different-name', CURRENT_TIMESTAMP, NULL)"
            )
        )
    engine.dispose()

    with pytest.raises(RuntimeError, match="本地身份与用户名不一致"):
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


def test_identity_split_can_downgrade_without_losing_legacy_account_columns(tmp_path: Path) -> None:
    url = sqlite_url(tmp_path / "identity-rollback.db")
    upgrade_database(url)
    engine = create_engine(url)
    with Session(engine) as session:
        session.add(
            User(
                id="rollback-user",
                username="rollback",
                password_hash="hash",
                phone_hmac="d" * 64,
                phone_masked="+86******0003",
            )
        )
        session.commit()
    engine.dispose()

    command.downgrade(alembic_config(url), "20261020_0002")

    downgraded_engine = create_engine(url)
    try:
        schema = inspect(downgraded_engine)
        assert "verified_phones" not in schema.get_table_names()
        identity_columns = {item["name"] for item in schema.get_columns("user_identities")}
        assert "credential_hash" not in identity_columns
        assert "created_at" not in identity_columns
        with downgraded_engine.connect() as connection:
            assert (
                connection.scalar(text("SELECT username FROM users WHERE id = 'rollback-user'"))
                == "rollback"
            )
    finally:
        downgraded_engine.dispose()


def test_phone_protection_migration_marks_unrecoverable_rows_and_can_downgrade(
    tmp_path: Path,
) -> None:
    url = sqlite_url(tmp_path / "phone-protection.db")
    command.upgrade(alembic_config(url), "20261020_0003")
    engine = create_engine(url)
    with Session(engine) as session:
        session.add(
            User(
                id="legacy-phone-user",
                username="legacy-phone",
                password_hash="hash",
                phone_hmac="e" * 64,
                phone_masked="+86******0004",
            )
        )
        session.commit()
    with engine.begin() as connection:
        connection.execute(
            text(
                "INSERT INTO verified_phones "
                "(id, user_id, phone_hmac, phone_masked, verification_source, "
                "verified_at, created_at) VALUES "
                "('legacy-phone', 'legacy-phone-user', :phone_hmac, "
                "'+86******0004', 'legacy', CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)"
            ),
            {"phone_hmac": "e" * 64},
        )
    engine.dispose()

    command.upgrade(alembic_config(url), "head")
    migrated = create_engine(url)
    try:
        with migrated.connect() as connection:
            row = (
                connection.execute(
                    text(
                        "SELECT hmac_key_id, encryption_status, phone_ciphertext, "
                        "encryption_key_id FROM verified_phones WHERE id = 'legacy-phone'"
                    )
                )
                .mappings()
                .one()
            )
        assert row["hmac_key_id"] == "legacy-v1"
        assert row["encryption_status"] == "unavailable"
        assert row["phone_ciphertext"] is None
        assert row["encryption_key_id"] is None
    finally:
        migrated.dispose()

    command.downgrade(alembic_config(url), "20261020_0003")
    downgraded = create_engine(url)
    try:
        columns = {item["name"] for item in inspect(downgraded).get_columns("verified_phones")}
        assert "hmac_key_id" not in columns
        assert "phone_ciphertext" not in columns
        assert "encryption_key_id" not in columns
        assert "encryption_status" not in columns
    finally:
        downgraded.dispose()
