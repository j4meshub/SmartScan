from __future__ import annotations

import base64

import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from services.api.app.config import Settings
from services.api.app.database import Base
from services.api.app.models import PhoneEncryptionStatus, User, VerifiedPhone
from services.api.app.phone_protection import (
    PhoneProtectionError,
    decrypt_phone,
    phone_needs_rotation,
    protect_phone,
    rotate_verified_phone,
)
from services.api.app.phone_rotation import rotate_phone_batch
from services.api.app.security import phone_hmac_candidates


def encoded_key(byte: bytes) -> str:
    return base64.urlsafe_b64encode(byte * 32).decode()


def protection_settings(*, active: str) -> Settings:
    return Settings(
        _env_file=None,
        phone_hmac_active_key_id=active,
        phone_hmac_peppers={"old": "o" * 32, "new": "n" * 32},
        phone_encryption_active_key_id=active,
        phone_encryption_keys={"old": encoded_key(b"1"), "new": encoded_key(b"2")},
    )


def phone_row(user: User, protected) -> VerifiedPhone:
    return VerifiedPhone(
        user_id=user.id,
        user=user,
        phone_hmac=protected.phone_hmac,
        hmac_key_id=protected.hmac_key_id,
        phone_masked=protected.phone_masked,
        phone_ciphertext=protected.phone_ciphertext,
        encryption_key_id=protected.encryption_key_id,
        encryption_status=PhoneEncryptionStatus.encrypted,
        verification_source="test",
    )


def test_authenticated_phone_encryption_is_randomized_and_bound_to_user() -> None:
    settings = protection_settings(active="old")
    first = protect_phone("+8613800138000", user_id="user-a", settings=settings)
    second = protect_phone("+8613800138000", user_id="user-a", settings=settings)
    user = User(
        id="user-a",
        username="legacy",
        password_hash="hash",
        phone_hmac=first.phone_hmac,
        phone_masked=first.phone_masked,
    )
    row = phone_row(user, first)

    assert first.phone_hmac == second.phone_hmac
    assert first.phone_ciphertext != second.phone_ciphertext
    assert decrypt_phone(row, settings=settings) == "+8613800138000"

    row.user_id = "user-b"
    with pytest.raises(PhoneProtectionError, match="phone_ciphertext_invalid") as exc_info:
        decrypt_phone(row, settings=settings)
    assert "+8613800138000" not in str(exc_info.value)
    assert first.phone_ciphertext not in str(exc_info.value)


def test_tampered_ciphertext_fails_without_sensitive_error_content() -> None:
    settings = protection_settings(active="old")
    protected = protect_phone("+15551234567", user_id="user-a", settings=settings)
    user = User(
        id="user-a",
        username="legacy",
        password_hash="hash",
        phone_hmac=protected.phone_hmac,
        phone_masked=protected.phone_masked,
    )
    row = phone_row(user, protected)
    payload = bytearray(base64.urlsafe_b64decode(row.phone_ciphertext or ""))
    payload[-1] ^= 1
    row.phone_ciphertext = base64.urlsafe_b64encode(payload).decode()

    with pytest.raises(PhoneProtectionError, match="phone_ciphertext_invalid") as exc_info:
        decrypt_phone(row, settings=settings)
    message = str(exc_info.value)
    assert "+15551234567" not in message
    assert settings.phone_hmac_peppers["old"] not in message


def test_rotation_reads_old_keys_and_updates_ciphertext_hmac_and_legacy_fields() -> None:
    old_settings = protection_settings(active="old")
    new_settings = protection_settings(active="new")
    protected = protect_phone("+8613900139000", user_id="user-a", settings=old_settings)
    user = User(
        id="user-a",
        username="legacy",
        password_hash="hash",
        phone_hmac=protected.phone_hmac,
        phone_masked=protected.phone_masked,
    )
    row = phone_row(user, protected)

    assert phone_needs_rotation(row, settings=new_settings)
    rotate_verified_phone(row, settings=new_settings)

    assert row.hmac_key_id == "new"
    assert row.encryption_key_id == "new"
    assert row.phone_hmac == user.phone_hmac
    assert row.phone_masked == user.phone_masked
    assert decrypt_phone(row, settings=new_settings) == "+8613900139000"
    assert not phone_needs_rotation(row, settings=new_settings)


def test_hmac_candidates_cover_active_and_retained_versions() -> None:
    candidates = phone_hmac_candidates(
        "+8613800138000",
        settings=protection_settings(active="new"),
    )
    assert set(candidates) == {"old", "new"}
    assert candidates["old"] != candidates["new"]


def test_unencrypted_legacy_phone_requires_reverification() -> None:
    row = VerifiedPhone(
        user_id="legacy-user",
        phone_hmac="a" * 64,
        hmac_key_id="legacy-v1",
        phone_masked="+86****8000",
        phone_ciphertext=None,
        encryption_key_id=None,
        encryption_status=PhoneEncryptionStatus.unavailable,
        verification_source="legacy",
    )
    with pytest.raises(PhoneProtectionError, match="phone_reverification_required"):
        decrypt_phone(row, settings=protection_settings(active="new"))


def test_production_phone_keyring_validation_is_strict_and_redacted() -> None:
    missing = Settings(
        _env_file=None,
        env="production",
        secret_key="s" * 32,
        phone_pepper="p" * 32,
        superadmin_password="strong-bootstrap-password",
    )
    with pytest.raises(RuntimeError, match="active phone encryption key is missing"):
        missing.validate_production()

    invalid_secret = "not-base64-secret-value"
    malformed = Settings(
        _env_file=None,
        env="production",
        secret_key="s" * 32,
        phone_hmac_peppers={"v1": "p" * 32},
        phone_hmac_active_key_id="v1",
        phone_encryption_keys={"v1": invalid_secret},
        phone_encryption_active_key_id="v1",
        superadmin_password="strong-bootstrap-password",
    )
    with pytest.raises(RuntimeError) as exc_info:
        malformed.validate_production()
    assert invalid_secret not in str(exc_info.value)


def test_rotation_batch_defaults_to_dry_run_and_counts_unrecoverable_rows() -> None:
    old_settings = protection_settings(active="old")
    new_settings = protection_settings(active="new")
    engine = create_engine("sqlite://")
    Base.metadata.create_all(engine)
    try:
        with Session(engine) as db:
            protected = protect_phone(
                "+8613700137000",
                user_id="recoverable-user",
                settings=old_settings,
            )
            recoverable_user = User(
                id="recoverable-user",
                username="recoverable",
                password_hash="hash",
                phone_hmac=protected.phone_hmac,
                phone_masked=protected.phone_masked,
            )
            recoverable = phone_row(recoverable_user, protected)
            protected_second = protect_phone(
                "+8613700137002",
                user_id="recoverable-user-2",
                settings=old_settings,
            )
            recoverable_user_second = User(
                id="recoverable-user-2",
                username="recoverable-2",
                password_hash="hash",
                phone_hmac=protected_second.phone_hmac,
                phone_masked=protected_second.phone_masked,
            )
            recoverable_second = phone_row(recoverable_user_second, protected_second)
            legacy_user = User(
                id="unrecoverable-user",
                username="unrecoverable",
                password_hash="hash",
                phone_hmac="f" * 64,
                phone_masked="+86****7001",
            )
            legacy = VerifiedPhone(
                user_id=legacy_user.id,
                user=legacy_user,
                phone_hmac=legacy_user.phone_hmac,
                hmac_key_id="legacy-v1",
                phone_masked=legacy_user.phone_masked,
                phone_ciphertext=None,
                encryption_key_id=None,
                encryption_status=PhoneEncryptionStatus.unavailable,
                verification_source="legacy",
            )
            db.add_all([recoverable, recoverable_second, legacy])
            db.commit()

            plan = rotate_phone_batch(db, limit=1, apply=False, settings=new_settings)
            db.refresh(recoverable)
            assert plan.examined == 3
            assert plan.rotated == 1
            assert plan.requires_reverification == 1
            assert recoverable.encryption_key_id == "old"

            applied = rotate_phone_batch(db, limit=1, apply=True, settings=new_settings)
            db.refresh(recoverable)
            db.refresh(recoverable_second)
            assert applied.rotated == 1
            assert (
                sum(item.encryption_key_id == "new" for item in (recoverable, recoverable_second))
                == 1
            )

            second_batch = rotate_phone_batch(db, limit=1, apply=True, settings=new_settings)
            db.refresh(recoverable)
            db.refresh(recoverable_second)
            assert second_batch.rotated == 1
            assert recoverable.encryption_key_id == "new"
            assert recoverable_second.encryption_key_id == "new"
            assert decrypt_phone(recoverable, settings=new_settings) == "+8613700137000"
            assert decrypt_phone(recoverable_second, settings=new_settings) == "+8613700137002"
            assert rotate_phone_batch(db, limit=1, apply=False, settings=new_settings).rotated == 0
    finally:
        engine.dispose()
