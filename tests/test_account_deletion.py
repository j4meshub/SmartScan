from __future__ import annotations

import hashlib
import io
import uuid
from datetime import UTC, datetime, timedelta

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import account_deletion, main
from services.api.app.account_deletion import process_account_deletion
from services.api.app.database import SessionLocal
from services.api.app.models import (
    AccountDeletionRequest,
    AccountDeletionStatus,
    AuditLog,
    JobStatus,
    PhoneReuseQuarantine,
    ProcessingJob,
    Role,
    ScanProject,
    SessionToken,
    UploadChunk,
    UploadSession,
    User,
    UserIdentity,
    UserStatus,
    VerifiedPhone,
)
from services.api.app.wecom import WeComIdentity
from services.api.app.wecom_auth import WeComAuthError, resolve_wecom_identity


def unique_phone() -> str:
    return f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"


def register(client: TestClient, phone: str) -> tuple[str, str, dict[str, str]]:
    username = f"delete_{uuid.uuid4().hex[:10]}"
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
    body = response.json()
    with SessionLocal() as db:
        identity = db.scalar(select(UserIdentity).where(UserIdentity.provider_subject == username))
        assert identity is not None
        user_id = identity.user_id
    return user_id, username, {"Authorization": f"Bearer {body['access_token']}"}


def sms_challenge(client: TestClient, phone: str, purpose: str) -> str:
    response = client.post(
        "/v1/auth/sms/challenges",
        json={"phone": phone, "purpose": purpose},
    )
    assert response.status_code == 201, response.text
    return response.json()["challenge_id"]


def request_deletion(
    client: TestClient,
    *,
    phone: str,
    headers: dict[str, str],
) -> dict[str, object]:
    challenge_id = sms_challenge(client, phone, "account_deletion")
    response = client.post(
        "/v1/me/account-deletion",
        headers=headers,
        json={
            "phone": phone,
            "sms_challenge_id": challenge_id,
            "sms_code": main.settings.dev_sms_code,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (64, 96), "white")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_account_deletion_request_revokes_sessions_and_can_be_canceled() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        _, username, headers = register(client, phone)
        deletion = request_deletion(client, phone=phone, headers=headers)
        assert deletion["status"] == "pending"
        execute_after = datetime.fromisoformat(str(deletion["execute_after"]))
        requested_at = datetime.fromisoformat(str(deletion["requested_at"]))
        assert timedelta(days=6, hours=23) <= execute_after - requested_at <= timedelta(days=7)
        assert client.get("/v1/me", headers=headers).status_code == 401
        assert (
            client.post(
                "/v1/auth/login",
                json={"username": username, "password": "correct-horse-battery-staple"},
            ).status_code
            == 403
        )

        cancel_challenge = sms_challenge(client, phone, "account_deletion_cancel")
        canceled = client.post(
            "/v1/auth/account-deletion/cancel",
            json={
                "phone": phone,
                "sms_challenge_id": cancel_challenge,
                "sms_code": main.settings.dev_sms_code,
            },
        )
        assert canceled.status_code == 200, canceled.text
        assert canceled.json()["status"] == "canceled"
        relogin = client.post(
            "/v1/auth/login",
            json={"username": username, "password": "correct-horse-battery-staple"},
        )
        assert relogin.status_code == 200, relogin.text
        requested_again = request_deletion(
            client,
            phone=phone,
            headers={"Authorization": f"Bearer {relogin.json()['access_token']}"},
        )
        assert requested_again["id"] == deletion["id"]
        assert requested_again["status"] == "pending"


def test_due_deletion_purges_resources_and_quarantines_phone() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        user_id, username, headers = register(client, phone)
        project = client.post(
            "/v1/projects",
            headers=headers,
            json={"title": "待删除项目", "mode": "document", "reading_order": "ltr"},
        )
        assert project.status_code == 201, project.text
        page = client.post(
            f"/v1/projects/{project.json()['id']}/pages",
            headers=headers,
            files={"file": ("delete.jpg", jpeg_bytes(), "image/jpeg")},
        )
        assert page.status_code == 202, page.text
        pending_image = jpeg_bytes()
        pending_upload = client.post(
            "/v1/uploads",
            headers=headers,
            json={
                "project_id": project.json()["id"],
                "file_name": "pending.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": len(pending_image),
                "sha256": hashlib.sha256(pending_image).hexdigest(),
                "idempotency_key": f"delete-{uuid.uuid4().hex}",
            },
        )
        assert pending_upload.status_code == 201, pending_upload.text
        pending_upload_id = pending_upload.json()["id"]
        chunk = client.put(
            f"/v1/uploads/{pending_upload_id}/chunks/0",
            headers={
                **headers,
                "X-Chunk-Sha256": hashlib.sha256(pending_image).hexdigest(),
            },
            content=pending_image,
        )
        assert chunk.status_code == 200, chunk.text
        deletion = request_deletion(client, phone=phone, headers=headers)

    now = datetime.now(UTC) + timedelta(days=8)
    with SessionLocal() as db:
        row = db.get(AccountDeletionRequest, deletion["id"])
        assert row is not None
        row.execute_after = now - timedelta(seconds=1)
        db.commit()
        result = process_account_deletion(db, row.id, now=now, settings=main.settings)
        assert result.status == AccountDeletionStatus.completed

    with SessionLocal() as db:
        user = db.get(User, user_id)
        deletion_row = db.get(AccountDeletionRequest, deletion["id"])
        quarantine = db.scalar(
            select(PhoneReuseQuarantine).where(
                PhoneReuseQuarantine.deletion_request_id == deletion["id"]
            )
        )
        assert user is not None and user.status == UserStatus.deleted
        assert user.username == f"deleted-{user_id}"
        assert user.phone_masked == "已删除"
        assert deletion_row is not None and deletion_row.status == AccountDeletionStatus.completed
        assert quarantine is not None
        assert db.scalar(select(UserIdentity).where(UserIdentity.user_id == user_id)) is None
        assert db.scalar(select(VerifiedPhone).where(VerifiedPhone.user_id == user_id)) is None
        assert db.scalar(select(SessionToken).where(SessionToken.user_id == user_id)) is None
        assert db.scalar(select(ScanProject).where(ScanProject.owner_user_id == user_id)) is None
        assert (
            db.scalar(select(ProcessingJob).where(ProcessingJob.owner_user_id == user_id)) is None
        )
        assert (
            db.scalar(select(UploadSession).where(UploadSession.owner_user_id == user_id)) is None
        )
        assert (
            db.scalar(select(UploadChunk).where(UploadChunk.upload_id == pending_upload_id)) is None
        )
        assert (
            db.scalar(
                select(AuditLog).where(
                    AuditLog.target_user_id == user_id,
                    AuditLog.action == "purge_account_data",
                )
            )
            is not None
        )
        with pytest.raises(WeComAuthError, match="wecom_phone_temporarily_unavailable"):
            resolve_wecom_identity(
                db,
                WeComIdentity(
                    corp_id="deleted-corp",
                    user_id=f"new-{uuid.uuid4().hex}",
                    phone_e164=phone,
                    assurance="trusted_mobile",
                ),
            )
        db.rollback()
        quarantine = db.scalar(
            select(PhoneReuseQuarantine).where(
                PhoneReuseQuarantine.deletion_request_id == deletion["id"]
            )
        )
        assert quarantine is not None
        quarantine.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
    assert not (main.settings.storage_root / "users" / user_id).exists()

    with TestClient(main.app) as client:
        blocked_user = f"blocked_{uuid.uuid4().hex[:10]}"
        with SessionLocal() as db:
            quarantine = db.scalar(
                select(PhoneReuseQuarantine).where(
                    PhoneReuseQuarantine.deletion_request_id == deletion["id"]
                )
            )
            assert quarantine is not None
            quarantine.expires_at = datetime.now(UTC) + timedelta(days=1)
            db.commit()
        blocked = client.post(
            "/v1/auth/register",
            json={
                "phone": phone,
                "sms_code": main.settings.dev_sms_code,
                "username": blocked_user,
                "password": "correct-horse-battery-staple",
                "locale": "zh-CN",
            },
        )
        assert blocked.status_code == 403
        assert blocked.json()["detail"] == "phone temporarily unavailable"

        with SessionLocal() as db:
            quarantine = db.scalar(
                select(PhoneReuseQuarantine).where(
                    PhoneReuseQuarantine.deletion_request_id == deletion["id"]
                )
            )
            assert quarantine is not None
            quarantine.expires_at = datetime.now(UTC) - timedelta(seconds=1)
            db.commit()
        registered_again = client.post(
            "/v1/auth/register",
            json={
                "phone": phone,
                "sms_code": main.settings.dev_sms_code,
                "username": username,
                "password": "correct-horse-battery-staple",
                "locale": "zh-CN",
            },
        )
        assert registered_again.status_code == 201, registered_again.text


def test_file_cleanup_failure_is_retryable(monkeypatch) -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        user_id, _, headers = register(client, phone)
        user_directory = main.settings.storage_root / "users" / user_id
        user_directory.mkdir(parents=True, exist_ok=True)
        (user_directory / "private.txt").write_text("private", encoding="utf-8")
        deletion = request_deletion(client, phone=phone, headers=headers)

    now = datetime.now(UTC) + timedelta(days=8)
    original_rmtree = account_deletion.shutil.rmtree

    def fail_cleanup(*_args, **_kwargs):
        raise OSError("simulated cleanup failure")

    monkeypatch.setattr(account_deletion.shutil, "rmtree", fail_cleanup)
    with SessionLocal() as db:
        row = db.get(AccountDeletionRequest, deletion["id"])
        assert row is not None
        row.execute_after = now - timedelta(seconds=1)
        db.commit()
        first = process_account_deletion(db, row.id, now=now, settings=main.settings)
        assert first.status == AccountDeletionStatus.cleanup_pending
    quarantine_path = main.settings.storage_root / ".account-deletion" / deletion["id"]
    assert quarantine_path.exists()

    monkeypatch.setattr(account_deletion.shutil, "rmtree", original_rmtree)
    with SessionLocal() as db:
        second = process_account_deletion(
            db,
            deletion["id"],
            now=now + timedelta(minutes=1),
            settings=main.settings,
        )
        assert second.status == AccountDeletionStatus.completed
    assert not quarantine_path.exists()


def test_running_processing_job_defers_account_cleanup() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        user_id, _, headers = register(client, phone)
        project = client.post(
            "/v1/projects",
            headers=headers,
            json={"title": "运行中任务", "mode": "document", "reading_order": "ltr"},
        )
        assert project.status_code == 201
        page = client.post(
            f"/v1/projects/{project.json()['id']}/pages",
            headers=headers,
            files={"file": ("running.jpg", jpeg_bytes(), "image/jpeg")},
        )
        assert page.status_code == 202
        deletion = request_deletion(client, phone=phone, headers=headers)

    now = datetime.now(UTC) + timedelta(days=8)
    with SessionLocal() as db:
        request_row = db.get(AccountDeletionRequest, deletion["id"])
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.owner_user_id == user_id))
        assert request_row is not None and job is not None
        request_row.execute_after = now - timedelta(seconds=1)
        job.status = JobStatus.baseline_processing
        db.commit()
        deferred = process_account_deletion(
            db,
            request_row.id,
            now=now,
            settings=main.settings,
        )
        assert deferred.status == AccountDeletionStatus.pending
        assert db.get(User, user_id).status == UserStatus.deleting
        assert db.get(ScanProject, project.json()["id"]) is not None
        job = db.get(ProcessingJob, job.id)
        assert job is not None
        job.status = JobStatus.failed_final
        db.commit()
        completed = process_account_deletion(
            db,
            request_row.id,
            now=now + timedelta(minutes=1),
            settings=main.settings,
        )
        assert completed.status == AccountDeletionStatus.completed


def test_super_admin_cannot_request_self_deletion() -> None:
    phone = unique_phone()
    with TestClient(main.app) as client:
        user_id, _, headers = register(client, phone)
        with SessionLocal() as db:
            user = db.get(User, user_id)
            assert user is not None
            user.role = Role.super_admin
            db.commit()
        challenge_id = sms_challenge(client, phone, "account_deletion")
        response = client.post(
            "/v1/me/account-deletion",
            headers=headers,
            json={
                "phone": phone,
                "sms_challenge_id": challenge_id,
                "sms_code": main.settings.dev_sms_code,
            },
        )
        assert response.status_code == 403
        assert response.json()["detail"] == "super_admin_protected"


def test_account_deletion_cannot_use_another_users_verified_phone() -> None:
    first_phone = unique_phone()
    second_phone = unique_phone()
    with TestClient(main.app) as client:
        first_user_id, _, first_headers = register(client, first_phone)
        second_user_id, _, _ = register(client, second_phone)
        challenge_id = sms_challenge(client, second_phone, "account_deletion")
        response = client.post(
            "/v1/me/account-deletion",
            headers=first_headers,
            json={
                "phone": second_phone,
                "sms_challenge_id": challenge_id,
                "sms_code": main.settings.dev_sms_code,
            },
        )
        assert response.status_code == 400
        assert response.json()["detail"] == "account_deletion_phone_mismatch"
    with SessionLocal() as db:
        first_user = db.get(User, first_user_id)
        second_user = db.get(User, second_user_id)
        assert first_user is not None and first_user.status == UserStatus.active
        assert second_user is not None and second_user.status == UserStatus.active
