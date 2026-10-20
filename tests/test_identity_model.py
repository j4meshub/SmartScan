from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.models import User, UserIdentity, VerifiedPhone
from services.api.app.security import hash_password, verify_password


def register(client: TestClient, *, phone: str, username: str, password: str) -> str:
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": phone,
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": password,
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return response.json()["access_token"]


def test_registration_dual_writes_new_identity_and_verified_phone() -> None:
    suffix = uuid.uuid4().hex[:10]
    username = f"identity_{suffix}"
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    password = "correct-horse-battery-staple"

    with TestClient(main.app) as client:
        token = register(client, phone=phone, username=username, password=password)
        response = client.get("/v1/me", headers={"Authorization": f"Bearer {token}"})
        assert response.status_code == 200
        assert response.json()["username"] == username

    with SessionLocal() as db:
        identity = db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == "local",
                UserIdentity.provider_subject == username,
            )
        )
        assert identity is not None
        user = db.get(User, identity.user_id)
        phone_row = db.scalar(
            select(VerifiedPhone).where(VerifiedPhone.user_id == identity.user_id)
        )
        assert user is not None
        assert phone_row is not None
        assert verify_password(password, identity.credential_hash or "")
        assert identity.credential_hash == user.password_hash
        assert phone_row.phone_hmac == user.phone_hmac
        assert phone_row.phone_masked == user.phone_masked
        assert phone_row.verification_source == "development_sms"


def test_login_view_and_password_change_use_split_identity_data() -> None:
    suffix = uuid.uuid4().hex[:10]
    username = f"split_{suffix}"
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    old_password = "correct-horse-battery-staple"
    new_password = "another-correct-horse-battery"

    with TestClient(main.app) as client:
        register(client, phone=phone, username=username, password=old_password)
        with SessionLocal() as db:
            identity = db.scalar(
                select(UserIdentity).where(UserIdentity.provider_subject == username)
            )
            assert identity is not None
            user = db.get(User, identity.user_id)
            phone_row = db.scalar(
                select(VerifiedPhone).where(VerifiedPhone.user_id == identity.user_id)
            )
            assert user is not None and phone_row is not None
            expected_mask = phone_row.phone_masked
            user.username = f"legacy-stale-{suffix}"
            user.password_hash = hash_password("legacy-stale-password")
            user.phone_masked = "legacy-stale-mask"
            db.commit()

        login = client.post(
            "/v1/auth/login",
            json={"username": username, "password": old_password},
        )
        assert login.status_code == 200
        current_headers = {"Authorization": f"Bearer {login.json()['access_token']}"}
        me = client.get("/v1/me", headers=current_headers)
        assert me.status_code == 200
        assert me.json()["username"] == username
        assert me.json()["phone_masked"] == expected_mask

        changed = client.post(
            "/v1/me/password",
            json={"current_password": old_password, "new_password": new_password},
            headers=current_headers,
        )
        assert changed.status_code == 204
        assert (
            client.post(
                "/v1/auth/login",
                json={"username": username, "password": old_password},
            ).status_code
            == 401
        )
        assert (
            client.post(
                "/v1/auth/login",
                json={"username": username, "password": new_password},
            ).status_code
            == 200
        )

    with SessionLocal() as db:
        identity = db.scalar(select(UserIdentity).where(UserIdentity.provider_subject == username))
        assert identity is not None
        user = db.get(User, identity.user_id)
        assert user is not None
        assert identity.credential_hash == user.password_hash
        assert verify_password(new_password, identity.credential_hash or "")


def test_phone_conflict_uses_verified_phone_even_if_legacy_column_drifts() -> None:
    suffix = uuid.uuid4().hex[:10]
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    first_username = f"phone_a_{suffix}"

    with TestClient(main.app) as client:
        register(
            client,
            phone=phone,
            username=first_username,
            password="correct-horse-battery-staple",
        )
        with SessionLocal() as db:
            identity = db.scalar(
                select(UserIdentity).where(UserIdentity.provider_subject == first_username)
            )
            assert identity is not None
            user = db.get(User, identity.user_id)
            assert user is not None
            user.phone_hmac = uuid.uuid4().hex + uuid.uuid4().hex
            db.commit()

        duplicate = client.post(
            "/v1/auth/register",
            json={
                "phone": phone,
                "sms_code": main.settings.dev_sms_code,
                "username": f"phone_b_{suffix}",
                "password": "correct-horse-battery-staple",
                "locale": "zh-CN",
            },
        )
        assert duplicate.status_code == 409
        assert duplicate.json()["detail"] == "phone already registered; use account binding"
