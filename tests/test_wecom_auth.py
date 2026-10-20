from __future__ import annotations

import uuid
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import auth_routes, main
from services.api.app.database import SessionLocal
from services.api.app.models import UserIdentity, WeComBindingTicket, WeComOAuthState
from services.api.app.wecom import MockWeComAdapter, WeComIdentity


def unique_phone() -> str:
    return f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"


def register_local(client: TestClient, phone: str, username: str) -> None:
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": phone,
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text


def start_oauth(client: TestClient) -> tuple[str, str]:
    response = client.post("/v1/auth/wecom/authorize")
    assert response.status_code == 201, response.text
    assert "Path=/" in response.headers["set-cookie"]
    assert "HttpOnly" in response.headers["set-cookie"]
    assert "SameSite=lax" in response.headers["set-cookie"]
    url = response.json()["authorization_url"]
    parsed = urlparse(url)
    assert parsed.scheme == "https"
    assert parsed.netloc == "open.weixin.qq.com"
    state = parse_qs(parsed.query)["state"][0]
    return state, url


def enable_mock(monkeypatch, identities: dict[str, WeComIdentity]) -> None:
    monkeypatch.setattr(main.settings, "wecom_mode", "mock")
    monkeypatch.setattr(main.settings, "wecom_corp_id", "corp-test")
    monkeypatch.setattr(main.settings, "wecom_agent_id", "agent-test")
    monkeypatch.setattr(
        main.settings, "wecom_redirect_uri", "https://h5.example.test/wecom/callback"
    )
    monkeypatch.setattr(
        auth_routes,
        "create_wecom_adapter",
        lambda _: MockWeComAdapter(identities),
    )


def test_callback_binds_unique_verified_phone_and_state_is_one_time(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:10]
    phone = unique_phone()
    identity = WeComIdentity("corp-test", f"member-{suffix}", phone, "mock")
    enable_mock(monkeypatch, {"oauth-code": identity})

    with TestClient(main.app) as client:
        register_local(client, phone, f"local_{suffix}")
        state, _ = start_oauth(client)
        callback = client.get(
            "/v1/auth/wecom/callback",
            params={"code": "oauth-code", "state": state},
        )
        assert callback.status_code == 200, callback.text
        assert callback.json()["action"] == "bind_verified_phone"
        assert callback.json()["access_token"]
        assert callback.json()["refresh_token"]
        assert callback.json()["session_id"]
        assert callback.json()["device_id"]

        replay = client.get(
            "/v1/auth/wecom/callback",
            params={"code": "oauth-code", "state": state},
        )
        assert replay.status_code == 400
        assert replay.json()["detail"] == "wecom_state_consumed"

    with SessionLocal() as db:
        bound = db.scalar(
            select(UserIdentity).where(
                UserIdentity.provider == "wecom",
                UserIdentity.provider_subject == identity.provider_subject,
            )
        )
        assert bound is not None
        state_rows = db.scalars(select(WeComOAuthState)).all()
        assert all(row.state_hash != state for row in state_rows)


def test_callback_rejects_state_from_another_browser(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:10]
    identity = WeComIdentity("corp-test", f"member-{suffix}", unique_phone(), "mock")
    enable_mock(monkeypatch, {"oauth-code": identity})

    with TestClient(main.app) as owner, TestClient(main.app) as other:
        state, _ = start_oauth(owner)
        rejected = other.get(
            "/v1/auth/wecom/callback",
            params={"code": "oauth-code", "state": state},
        )
        assert rejected.status_code == 400
        assert rejected.json()["detail"] == "wecom_intent_invalid"

        accepted = owner.get(
            "/v1/auth/wecom/callback",
            params={"code": "oauth-code", "state": state},
        )
        assert accepted.status_code == 200, accepted.text


def test_missing_directory_phone_requires_sms_and_consumes_binding_ticket(monkeypatch) -> None:
    suffix = uuid.uuid4().hex[:10]
    phone = unique_phone()
    identity = WeComIdentity("corp-test", f"member-{suffix}", None, "mock")
    enable_mock(monkeypatch, {"without-phone": identity})

    with TestClient(main.app) as client:
        state, _ = start_oauth(client)
        callback = client.get(
            "/v1/auth/wecom/callback",
            params={"code": "without-phone", "state": state},
        )
        assert callback.status_code == 200, callback.text
        assert callback.json()["action"] == "require_phone_binding"
        ticket = callback.json()["binding_ticket"]
        assert ticket

        challenge = client.post(
            "/v1/auth/sms/challenges",
            json={"phone": phone, "purpose": "wecom_binding"},
        )
        assert challenge.status_code == 201, challenge.text
        payload = {
            "binding_ticket": ticket,
            "phone": phone,
            "sms_challenge_id": challenge.json()["challenge_id"],
            "sms_code": main.settings.dev_sms_code,
        }
        bound = client.post("/v1/auth/wecom/bind-phone", json=payload)
        assert bound.status_code == 200, bound.text
        assert bound.json()["access_token"]
        replay = client.post("/v1/auth/wecom/bind-phone", json=payload)
        assert replay.status_code == 400
        assert replay.json()["detail"] == "wecom_binding_ticket_consumed"

    with SessionLocal() as db:
        ticket_rows = db.scalars(select(WeComBindingTicket)).all()
        assert ticket_rows[-1].consumed_at is not None
        identity_row = db.scalar(
            select(UserIdentity).where(UserIdentity.provider_subject == identity.provider_subject)
        )
        assert identity_row is not None
