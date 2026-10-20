from __future__ import annotations

import uuid
from datetime import UTC, datetime, timedelta
from urllib.parse import quote

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.models import RefreshToken, SessionToken, User, UserIdentity, UserStatus


def unique_phone() -> str:
    return f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"


def device_headers(device_id: str, name: str) -> dict[str, str]:
    return {
        "x-device-id": device_id,
        "x-device-name": quote(name, safe=""),
        "x-device-platform": "android",
    }


def register(client: TestClient, *, device_id: str, name: str) -> tuple[str, dict[str, object]]:
    username = f"device_{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/v1/auth/register",
        headers=device_headers(device_id, name),
        json={
            "phone": unique_phone(),
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return username, response.json()


def test_refresh_rotates_tokens_and_replay_revokes_device_family() -> None:
    with TestClient(main.app) as client:
        _, issued = register(client, device_id=f"android:{uuid.uuid4()}", name="测试手机")
        assert issued["refresh_token"]
        assert issued["session_id"]
        assert issued["device_id"].startswith("android:")
        expires_at = datetime.fromisoformat(str(issued["expires_at"]))
        assert expires_at <= datetime.now(UTC) + timedelta(minutes=16)

        headers = {"Authorization": f"Bearer {issued['access_token']}"}
        sessions = client.get("/v1/me/sessions", headers=headers)
        assert sessions.status_code == 200, sessions.text
        assert sessions.json() == [
            {
                "id": issued["session_id"],
                "device_id": issued["device_id"],
                "device_name": "测试手机",
                "platform": "android",
                "current": True,
                "created_at": sessions.json()[0]["created_at"],
                "last_seen_at": sessions.json()[0]["last_seen_at"],
                "access_expires_at": sessions.json()[0]["access_expires_at"],
            }
        ]

        rotated = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": issued["refresh_token"]},
        )
        assert rotated.status_code == 200, rotated.text
        rotated_body = rotated.json()
        assert rotated_body["session_id"] == issued["session_id"]
        assert rotated_body["refresh_token"] != issued["refresh_token"]
        assert client.get("/v1/me", headers=headers).status_code == 401
        rotated_headers = {"Authorization": f"Bearer {rotated_body['access_token']}"}
        assert client.get("/v1/me", headers=rotated_headers).status_code == 200

        replay = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": issued["refresh_token"]},
        )
        assert replay.status_code == 401
        assert replay.json()["detail"] == "refresh_token_replayed"
        assert client.get("/v1/me", headers=rotated_headers).status_code == 401


def test_device_revoke_and_revoke_all_are_scoped_to_current_user() -> None:
    with TestClient(main.app) as client:
        username, first = register(
            client,
            device_id=f"android:{uuid.uuid4()}",
            name="第一台设备",
        )
        second_login = client.post(
            "/v1/auth/login",
            headers=device_headers(f"ios:{uuid.uuid4()}", "第二台设备"),
            json={
                "username": username,
                "password": "correct-horse-battery-staple",
            },
        )
        assert second_login.status_code == 200, second_login.text
        second = second_login.json()
        second_headers = {"Authorization": f"Bearer {second['access_token']}"}
        sessions = client.get("/v1/me/sessions", headers=second_headers)
        assert sessions.status_code == 200
        assert {item["device_name"] for item in sessions.json()} == {
            "第一台设备",
            "第二台设备",
        }

        revoked = client.delete(
            f"/v1/me/sessions/{first['session_id']}",
            headers=second_headers,
        )
        assert revoked.status_code == 204
        assert (
            client.get(
                "/v1/me",
                headers={"Authorization": f"Bearer {first['access_token']}"},
            ).status_code
            == 401
        )
        assert client.get("/v1/me", headers=second_headers).status_code == 200

        revoked_all = client.delete("/v1/me/sessions", headers=second_headers)
        assert revoked_all.status_code == 204
        assert client.get("/v1/me", headers=second_headers).status_code == 401


def test_device_session_idor_returns_not_found() -> None:
    with TestClient(main.app) as client:
        _, first = register(client, device_id=f"web:{uuid.uuid4()}", name="用户甲")
        _, second = register(client, device_id=f"web:{uuid.uuid4()}", name="用户乙")
        first_headers = {"Authorization": f"Bearer {first['access_token']}"}
        response = client.delete(
            f"/v1/me/sessions/{second['session_id']}",
            headers=first_headers,
        )
        assert response.status_code == 404
        assert response.json()["detail"] == "session not found"
        assert (
            client.get(
                "/v1/me",
                headers={"Authorization": f"Bearer {second['access_token']}"},
            ).status_code
            == 200
        )


def test_disabled_user_cannot_refresh_and_session_is_revoked() -> None:
    with TestClient(main.app) as client:
        username, issued = register(
            client,
            device_id=f"android:{uuid.uuid4()}",
            name="停用测试设备",
        )
        with SessionLocal() as db:
            identity = db.scalar(
                select(UserIdentity).where(UserIdentity.provider_subject == username)
            )
            assert identity is not None
            user = db.get(User, identity.user_id)
            assert user is not None
            user.status = UserStatus.disabled
            db.commit()

        refresh = client.post(
            "/v1/auth/refresh",
            json={"refresh_token": issued["refresh_token"]},
        )
        assert refresh.status_code == 401
        assert refresh.json()["detail"] == "account_unavailable"

    with SessionLocal() as db:
        session = db.get(SessionToken, issued["session_id"])
        assert session is not None and session.revoked_at is not None
        refresh_rows = db.scalars(
            select(RefreshToken).where(RefreshToken.session_id == session.id)
        ).all()
        assert refresh_rows and all(item.revoked_at is not None for item in refresh_rows)
