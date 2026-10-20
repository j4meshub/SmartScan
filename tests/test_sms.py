from __future__ import annotations

import base64
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import main
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.models import SmsChallenge, VerifiedPhone
from services.api.app.sms import (
    SmsProviderError,
    create_sms_provider,
)


def unique_phone() -> str:
    return f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"


def request_challenge(client: TestClient, phone: str, **headers: str) -> str:
    response = client.post(
        "/v1/auth/sms/challenges",
        json={"phone": phone, "purpose": "registration"},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    body = response.json()
    assert set(body) == {"challenge_id", "expires_at", "retry_after_seconds"}
    return body["challenge_id"]


def register_with_challenge(
    client: TestClient,
    *,
    phone: str,
    challenge_id: str,
    code: str,
    username: str,
):
    return client.post(
        "/v1/auth/register",
        json={
            "phone": phone,
            "sms_code": code,
            "sms_challenge_id": challenge_id,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )


def test_mock_challenge_stores_only_hash_and_register_consumes_once() -> None:
    phone = unique_phone()
    suffix = uuid.uuid4().hex[:10]
    with TestClient(main.app) as client:
        challenge_id = request_challenge(client, phone)
        registered = register_with_challenge(
            client,
            phone=phone,
            challenge_id=challenge_id,
            code=main.settings.dev_sms_code,
            username=f"sms_{suffix}",
        )
        assert registered.status_code == 201, registered.text
        replay = register_with_challenge(
            client,
            phone=unique_phone(),
            challenge_id=challenge_id,
            code=main.settings.dev_sms_code,
            username=f"sms_replay_{suffix}",
        )
        assert replay.status_code == 400
        assert replay.json()["detail"] == "sms_challenge_consumed"

    with SessionLocal() as db:
        challenge = db.get(SmsChallenge, challenge_id)
        assert challenge is not None
        assert challenge.code_hash != main.settings.dev_sms_code
        assert main.settings.dev_sms_code not in (challenge.provider_receipt or "")
        assert phone not in (challenge.provider_receipt or "")
        assert challenge.attempts == 1
        assert challenge.verified_at is not None
        assert challenge.consumed_at is not None
        verified = db.scalar(
            select(VerifiedPhone).where(VerifiedPhone.phone_hmac == challenge.phone_hmac)
        )
        assert verified is not None
        assert verified.verification_source == "development_mock"


def test_wrong_code_exhausts_five_attempts_and_cannot_be_reused() -> None:
    phone = unique_phone()
    suffix = uuid.uuid4().hex[:10]
    with TestClient(main.app) as client:
        challenge_id = request_challenge(client, phone)
        for attempt in range(5):
            response = register_with_challenge(
                client,
                phone=phone,
                challenge_id=challenge_id,
                code="000000",
                username=f"wrong_{suffix}_{attempt}",
            )
            assert response.status_code == 400
        assert response.json()["detail"] == "sms_challenge_attempts_exhausted"
        correct = register_with_challenge(
            client,
            phone=phone,
            challenge_id=challenge_id,
            code=main.settings.dev_sms_code,
            username=f"locked_{suffix}",
        )
        assert correct.status_code == 400
        assert correct.json()["detail"] == "sms_challenge_attempts_exhausted"

    with SessionLocal() as db:
        challenge = db.get(SmsChallenge, challenge_id)
        assert challenge is not None
        assert challenge.attempts == 5
        assert challenge.consumed_at is None


def test_expired_challenge_is_rejected() -> None:
    phone = unique_phone()
    suffix = uuid.uuid4().hex[:10]
    with TestClient(main.app) as client:
        challenge_id = request_challenge(client, phone)
        with SessionLocal() as db:
            challenge = db.get(SmsChallenge, challenge_id)
            assert challenge is not None
            challenge.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        response = register_with_challenge(
            client,
            phone=phone,
            challenge_id=challenge_id,
            code=main.settings.dev_sms_code,
            username=f"expired_{suffix}",
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "sms_challenge_expired"


def test_phone_rate_limit_and_forwarded_header_does_not_change_limit_ip() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        ids = [request_challenge(client, phone) for _ in range(3)]
        limited = client.post(
            "/v1/auth/sms/challenges",
            json={"phone": phone, "purpose": "registration"},
        )
        assert limited.status_code == 429
        assert limited.headers["retry-after"] == str(main.settings.sms_rate_window_seconds)

        first = request_challenge(client, unique_phone(), **{"x-forwarded-for": "1.1.1.1"})
        second = request_challenge(client, unique_phone(), **{"x-forwarded-for": "8.8.8.8"})

    with SessionLocal() as db:
        rows = [db.get(SmsChallenge, item) for item in [*ids, first, second]]
        assert all(row is not None for row in rows)
        assert rows[-1].requester_ip_hash == rows[-2].requester_ip_hash


def test_disabled_and_production_mock_provider_fail_safely() -> None:
    disabled = create_sms_provider(Settings(_env_file=None, sms_mode="disabled"))
    with pytest.raises(SmsProviderError, match="sms_provider_disabled"):
        disabled.send_verification(phone="+8613800138000", code="123456", challenge_id="id")

    production = Settings(
        _env_file=None,
        env="production",
        sms_mode="mock",
        secret_key="s" * 32,
        phone_hmac_peppers={"v1": "p" * 32},
        phone_hmac_active_key_id="v1",
        phone_encryption_keys={"v1": base64.urlsafe_b64encode(b"k" * 32).decode()},
        phone_encryption_active_key_id="v1",
        superadmin_password="strong-bootstrap-password",
    )
    with pytest.raises(RuntimeError, match="SMARTSCAN_SMS_MODE=mock"):
        production.validate_production()
