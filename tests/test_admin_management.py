from __future__ import annotations

import uuid

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.models import AuditLog, Role, User, UserIdentity


def unique_phone() -> str:
    return f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"


def register(client: TestClient, prefix: str) -> tuple[str, str, dict[str, str]]:
    username = f"{prefix}_{uuid.uuid4().hex[:10]}"
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": unique_phone(),
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        identity = db.scalar(select(UserIdentity).where(UserIdentity.provider_subject == username))
        assert identity is not None
        user_id = identity.user_id
    return user_id, username, {"Authorization": f"Bearer {response.json()['access_token']}"}


def assign_roles(role_by_user_id: dict[str, Role]) -> None:
    with SessionLocal() as db:
        users = db.scalars(select(User).where(User.id.in_(role_by_user_id))).all()
        for user in users:
            user.role = role_by_user_id[user.id]
        db.commit()


def test_user_listing_is_paginated_filtered_and_role_scoped() -> None:
    marker = f"adminlist_{uuid.uuid4().hex[:8]}"
    with TestClient(main.app) as client:
        first_id, _, _ = register(client, marker)
        second_id, _, _ = register(client, marker)
        admin_id, _, admin_headers = register(client, marker)
        other_admin_id, _, _ = register(client, marker)
        super_id, _, super_headers = register(client, marker)
        assign_roles(
            {
                admin_id: Role.admin,
                other_admin_id: Role.admin,
                super_id: Role.super_admin,
            }
        )

        first_page = client.get(
            f"/v1/admin/users?q={marker}&role=user&limit=1&offset=0",
            headers=admin_headers,
        )
        second_page = client.get(
            f"/v1/admin/users?q={marker}&role=user&limit=1&offset=1",
            headers=admin_headers,
        )
        assert first_page.status_code == 200
        assert second_page.status_code == 200
        assert first_page.headers["x-total-count"] == "2"
        assert {first_page.json()[0]["id"], second_page.json()[0]["id"]} == {
            first_id,
            second_id,
        }
        assert all(item["role"] == "user" for item in first_page.json() + second_page.json())

        super_view = client.get(
            f"/v1/admin/users?q={marker}&limit=20",
            headers=super_headers,
        )
        assert super_view.status_code == 200
        assert int(super_view.headers["x-total-count"]) == 5
        assert {item["role"] for item in super_view.json()} == {
            "user",
            "admin",
            "super_admin",
        }


def test_role_and_status_hierarchy_revokes_sessions_and_audits_denials() -> None:
    with TestClient(main.app) as client:
        target_id, _, target_headers = register(client, "adminmatrix_target")
        admin_id, _, admin_headers = register(client, "adminmatrix_admin")
        other_admin_id, _, _ = register(client, "adminmatrix_other")
        super_id, _, super_headers = register(client, "adminmatrix_super")
        assign_roles(
            {
                admin_id: Role.admin,
                other_admin_id: Role.admin,
                super_id: Role.super_admin,
            }
        )

        hidden_admin = client.patch(
            f"/v1/admin/users/{other_admin_id}/status",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert hidden_admin.status_code == 404
        disabled = client.patch(
            f"/v1/admin/users/{target_id}/status",
            headers=admin_headers,
            json={"status": "disabled"},
        )
        assert disabled.status_code == 200
        assert disabled.json()["status"] == "disabled"
        assert client.get("/v1/me", headers=target_headers).status_code == 401

        reactivated = client.patch(
            f"/v1/admin/users/{target_id}/status",
            headers=super_headers,
            json={"status": "active"},
        )
        assert reactivated.status_code == 200
        denied_promotion = client.patch(
            f"/v1/admin/users/{target_id}/role",
            headers=admin_headers,
            json={"role": "admin"},
        )
        assert denied_promotion.status_code == 404
        promoted = client.patch(
            f"/v1/admin/users/{target_id}/role",
            headers=super_headers,
            json={"role": "admin"},
        )
        assert promoted.status_code == 200
        assert promoted.json()["role"] == "admin"

    with SessionLocal() as db:
        denied = db.scalars(
            select(AuditLog).where(
                AuditLog.actor_user_id == admin_id,
                AuditLog.result == "denied",
                AuditLog.action.in_(("change_status", "change_role")),
            )
        ).all()
        assert {item.action for item in denied} == {"change_status", "change_role"}


def test_admin_can_revoke_regular_user_sessions_but_not_peer_sessions() -> None:
    with TestClient(main.app) as client:
        target_id, target_name, first_headers = register(client, "adminrevoke_target")
        second_login = client.post(
            "/v1/auth/login",
            json={
                "username": target_name,
                "password": "correct-horse-battery-staple",
            },
        )
        assert second_login.status_code == 200
        second_headers = {"Authorization": f"Bearer {second_login.json()['access_token']}"}
        admin_id, _, admin_headers = register(client, "adminrevoke_admin")
        peer_id, _, _ = register(client, "adminrevoke_peer")
        assign_roles({admin_id: Role.admin, peer_id: Role.admin})

        revoked = client.delete(
            f"/v1/admin/users/{target_id}/sessions",
            headers=admin_headers,
        )
        assert revoked.status_code == 204
        assert client.get("/v1/me", headers=first_headers).status_code == 401
        assert client.get("/v1/me", headers=second_headers).status_code == 401
        hidden_peer = client.delete(
            f"/v1/admin/users/{peer_id}/sessions",
            headers=admin_headers,
        )
        assert hidden_peer.status_code == 404


def test_admin_deletion_controls_and_audit_filters() -> None:
    with TestClient(main.app) as client:
        target_id, target_name, target_headers = register(client, "admindelete_target")
        admin_id, _, admin_headers = register(client, "admindelete_admin")
        peer_id, peer_name, _ = register(client, "admindelete_peer")
        regular_id, _, regular_headers = register(client, "admindelete_regular")
        assign_roles({admin_id: Role.admin, peer_id: Role.admin})

        mismatch = client.post(
            f"/v1/admin/users/{target_id}/account-deletion",
            headers=admin_headers,
            json={"confirm_username": "wrong-name", "reason": "测试确认不匹配"},
        )
        assert mismatch.status_code == 409
        created = client.post(
            f"/v1/admin/users/{target_id}/account-deletion",
            headers=admin_headers,
            json={"confirm_username": target_name, "reason": "用户提交正式删除申请"},
        )
        assert created.status_code == 202, created.text
        deletion = created.json()
        assert deletion["request_source"] == "admin"
        assert deletion["requested_by_user_id"] == admin_id
        assert client.get("/v1/me", headers=target_headers).status_code == 401

        listed = client.get(
            "/v1/admin/account-deletions?status=pending&limit=20",
            headers=admin_headers,
        )
        assert listed.status_code == 200
        assert deletion["id"] in {item["id"] for item in listed.json()}
        canceled = client.post(
            f"/v1/admin/account-deletions/{deletion['id']}/cancel",
            headers=admin_headers,
            json={"reason": "已复核，撤销删除"},
        )
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        assert canceled.json()["cancellation_reason"] == "已复核，撤销删除"

        hidden_peer = client.post(
            f"/v1/admin/users/{peer_id}/account-deletion",
            headers=admin_headers,
            json={"confirm_username": peer_name, "reason": "越权测试"},
        )
        assert hidden_peer.status_code == 404
        regular_denied = client.get("/v1/admin/users", headers=regular_headers)
        assert regular_denied.status_code == 403

        audits = client.get(
            f"/v1/admin/audit?action=admin_request_account_deletion&actor_user_id={admin_id}",
            headers=admin_headers,
        )
        assert audits.status_code == 200
        assert int(audits.headers["x-total-count"]) >= 3
        assert {item["result"] for item in audits.json()} == {"allowed", "denied"}

    with SessionLocal() as db:
        regular_attempt = db.scalar(
            select(AuditLog).where(
                AuditLog.actor_user_id == regular_id,
                AuditLog.action == "list_users",
                AuditLog.result == "denied",
            )
        )
        assert regular_attempt is not None
