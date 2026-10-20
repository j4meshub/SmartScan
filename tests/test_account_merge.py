from __future__ import annotations

import base64
import hashlib
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import delete, select

from services.api.app import account_merge, main
from services.api.app.account_merge import AccountMergeError
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.models import (
    AccountMergeAudit,
    JobStatus,
    PhoneEncryptionStatus,
    ProcessingJob,
    Role,
    ScanPage,
    ScanProject,
    SessionToken,
    SmsRateLimit,
    UploadChunk,
    UploadSession,
    UploadStatus,
    User,
    UserIdentity,
    UserStatus,
    VerifiedPhone,
)
from services.api.app.security import new_session, phone_hmac


def merge_settings() -> Settings:
    return Settings(
        _env_file=None,
        phone_hmac_active_key_id="new",
        phone_hmac_peppers={"old": "o" * 32, "new": "n" * 32},
        phone_encryption_active_key_id="new",
        phone_encryption_keys={
            "new": base64.urlsafe_b64encode(b"2" * 32).decode(),
        },
    )


def create_pair(
    phone: str,
    settings: Settings,
    *,
    overlapping_provider: bool = False,
    with_files: bool = True,
) -> tuple[str, str, str, list[Path]]:
    canonical_id = str(uuid.uuid4())
    source_id = str(uuid.uuid4())
    project_id = str(uuid.uuid4())
    page_id = str(uuid.uuid4())
    upload_id = str(uuid.uuid4())
    raw_token, token_digest, token_expires = new_session()
    old_digest = phone_hmac(phone, key_id="old", settings=settings)
    new_digest = phone_hmac(phone, key_id="new", settings=settings)
    now = datetime.now(UTC)
    paths: list[Path] = []
    with SessionLocal() as db:
        canonical = User(
            id=canonical_id,
            username=f"canonical_{uuid.uuid4().hex[:8]}",
            password_hash="not-used",
            phone_hmac=old_digest,
            phone_masked="+15****0001",
            role=Role.user,
            status=UserStatus.active,
            created_at=now - timedelta(days=10),
        )
        source = User(
            id=source_id,
            username=f"source_{uuid.uuid4().hex[:8]}",
            password_hash="not-used",
            phone_hmac=new_digest,
            phone_masked="+15****0001",
            role=Role.user,
            status=UserStatus.active,
            created_at=now - timedelta(days=1),
        )
        db.add_all((canonical, source))
        db.add_all(
            (
                UserIdentity(
                    user_id=canonical_id,
                    provider="local",
                    provider_subject=canonical.username,
                    credential_hash="not-used",
                ),
                UserIdentity(
                    user_id=source_id,
                    provider="local" if overlapping_provider else "wecom",
                    provider_subject=(
                        source.username if overlapping_provider else f"corp:{source_id}"
                    ),
                    credential_hash="not-used" if overlapping_provider else None,
                ),
                VerifiedPhone(
                    user_id=canonical_id,
                    phone_hmac=old_digest,
                    hmac_key_id="old",
                    phone_masked=canonical.phone_masked,
                    encryption_status=PhoneEncryptionStatus.unavailable,
                    verification_source="legacy",
                ),
                VerifiedPhone(
                    user_id=source_id,
                    phone_hmac=new_digest,
                    hmac_key_id="new",
                    phone_masked=source.phone_masked,
                    encryption_status=PhoneEncryptionStatus.unavailable,
                    verification_source="sms",
                ),
                SessionToken(
                    user_id=source_id,
                    token_hash=token_digest,
                    expires_at=token_expires,
                ),
            )
        )
        if with_files:
            original_relative = f"users/{source_id}/originals/{project_id}/{page_id}.jpg"
            processed_relative = f"users/{source_id}/processed/{project_id}/{page_id}.jpg"
            chunk_relative = f"users/{source_id}/temp/{upload_id}/00000000.part"
            original = main.settings.storage_root / original_relative
            processed = main.settings.storage_root / processed_relative
            chunk_path = main.settings.storage_root / chunk_relative
            original.parent.mkdir(parents=True, exist_ok=True)
            processed.parent.mkdir(parents=True, exist_ok=True)
            chunk_path.parent.mkdir(parents=True, exist_ok=True)
            original_data = b"original-account-merge-image"
            processed_data = b"processed-account-merge-image"
            chunk_data = b"completed-upload-chunk"
            original.write_bytes(original_data)
            processed.write_bytes(processed_data)
            chunk_path.write_bytes(chunk_data)
            paths = [original, processed, chunk_path]
            db.add(ScanProject(id=project_id, owner_user_id=source_id, title="待合并项目"))
            db.add(
                ScanPage(
                    id=page_id,
                    project_id=project_id,
                    owner_user_id=source_id,
                    page_number=1,
                    original_path=original_relative,
                    processed_path=processed_relative,
                    sha256=hashlib.sha256(original_data).hexdigest(),
                    size_bytes=len(original_data),
                    mime_type="image/jpeg",
                )
            )
            db.add(
                UploadSession(
                    id=upload_id,
                    owner_user_id=source_id,
                    project_id=project_id,
                    idempotency_key=f"upload-{uuid.uuid4().hex}",
                    file_name="page.jpg",
                    mime_type="image/jpeg",
                    size_bytes=len(chunk_data),
                    expected_sha256=hashlib.sha256(chunk_data).hexdigest(),
                    chunk_size=len(chunk_data),
                    total_chunks=1,
                    status=UploadStatus.completed,
                    page_id=page_id,
                    expires_at=now + timedelta(hours=1),
                )
            )
            db.add(
                UploadChunk(
                    upload_id=upload_id,
                    chunk_index=0,
                    size_bytes=len(chunk_data),
                    sha256=hashlib.sha256(chunk_data).hexdigest(),
                    relative_path=chunk_relative,
                )
            )
            db.add(
                ProcessingJob(
                    owner_user_id=source_id,
                    project_id=project_id,
                    page_id=page_id,
                    kind="document",
                    status=JobStatus.pending,
                )
            )
        db.commit()
    return canonical_id, source_id, raw_token, paths


def request_challenge(client: TestClient, phone: str) -> str:
    response = client.post(
        "/v1/auth/sms/challenges",
        json={"phone": phone, "purpose": "account_merge"},
    )
    assert response.status_code == 201, response.text
    with SessionLocal() as db:
        db.execute(delete(SmsRateLimit))
        db.commit()
    return response.json()["challenge_id"]


def merge_payload(phone: str, challenge_id: str, idempotency_key: str) -> dict[str, str]:
    return {
        "phone": phone,
        "sms_challenge_id": challenge_id,
        "sms_code": main.settings.dev_sms_code,
        "idempotency_key": idempotency_key,
    }


def create_outsider_session() -> str:
    user_id = str(uuid.uuid4())
    raw_token, token_digest, token_expires = new_session()
    with SessionLocal() as db:
        db.add(
            User(
                id=user_id,
                username=f"outsider_{uuid.uuid4().hex[:8]}",
                password_hash="not-used",
                phone_hmac=hashlib.sha256(user_id.encode()).hexdigest(),
                phone_masked="+15****9999",
                role=Role.user,
                status=UserStatus.active,
            )
        )
        db.add(
            SessionToken(
                user_id=user_id,
                token_hash=token_digest,
                expires_at=token_expires,
            )
        )
        db.commit()
    return raw_token


def test_merge_moves_resources_files_and_revokes_sessions(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = merge_settings()
    monkeypatch.setattr(account_merge, "get_settings", lambda: settings)
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    idempotency_key = f"merge-{uuid.uuid4().hex}"

    with TestClient(main.app) as client:
        canonical_id, source_id, token, source_paths = create_pair(phone, settings)
        challenge_id = request_challenge(client, phone)
        response = client.post(
            "/v1/auth/account-merges",
            json=merge_payload(phone, challenge_id, idempotency_key),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["canonical_user_id"] == canonical_id
        assert result["source_user_id"] == source_id
        assert result["require_reauthentication"] is True
        assert client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 401

    with SessionLocal() as db:
        source = db.get(User, source_id)
        assert source is not None and source.status == UserStatus.deleted
        assert db.scalar(select(VerifiedPhone).where(VerifiedPhone.user_id == source_id)) is None
        assert {
            item.user_id
            for item in db.scalars(
                select(UserIdentity).where(UserIdentity.provider.in_(("local", "wecom")))
            )
            if item.user_id in (canonical_id, source_id)
        } == {canonical_id}
        project = db.scalar(select(ScanProject).where(ScanProject.title == "待合并项目"))
        assert project is not None and project.owner_user_id == canonical_id
        page = db.scalar(select(ScanPage).where(ScanPage.project_id == project.id))
        assert page is not None and page.owner_user_id == canonical_id
        assert page.original_path.startswith(f"users/{canonical_id}/")
        assert page.processed_path and page.processed_path.startswith(f"users/{canonical_id}/")
        upload = db.scalar(select(UploadSession).where(UploadSession.project_id == project.id))
        assert upload is not None and upload.owner_user_id == canonical_id
        job = db.scalar(select(ProcessingJob).where(ProcessingJob.project_id == project.id))
        assert job is not None and job.owner_user_id == canonical_id
        audit = db.scalar(
            select(AccountMergeAudit).where(AccountMergeAudit.idempotency_key == idempotency_key)
        )
        assert audit is not None and audit.result == "completed"
        replay_token, replay_digest, replay_expires = new_session()
        db.add(
            SessionToken(
                user_id=canonical_id,
                token_hash=replay_digest,
                expires_at=replay_expires,
            )
        )
        db.commit()

    with TestClient(main.app) as client:
        replay = client.post(
            "/v1/auth/account-merges",
            json=merge_payload(phone, challenge_id, idempotency_key),
            headers={"Authorization": f"Bearer {replay_token}"},
        )
        assert replay.status_code == 200, replay.text
        assert replay.json()["merge_id"] == result["merge_id"]

    for source_path in source_paths:
        assert not source_path.exists()
        relative = source_path.relative_to(main.settings.storage_root)
        canonical_path = main.settings.storage_root / Path(
            "users", canonical_id, *relative.parts[2:]
        )
        assert canonical_path.is_file()


def test_merge_rejects_overlapping_identity_provider(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = merge_settings()
    monkeypatch.setattr(account_merge, "get_settings", lambda: settings)
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    with TestClient(main.app) as client:
        _, source_id, token, _ = create_pair(
            phone,
            settings,
            overlapping_provider=True,
            with_files=False,
        )
        challenge_id = request_challenge(client, phone)
        response = client.post(
            "/v1/auth/account-merges",
            json=merge_payload(phone, challenge_id, f"merge-{uuid.uuid4().hex}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "account_merge_identity_conflict"
        assert client.get("/v1/me", headers={"Authorization": f"Bearer {token}"}).status_code == 200

    with SessionLocal() as db:
        source = db.get(User, source_id)
        assert source is not None and source.status == UserStatus.active


def test_outsider_cannot_merge_other_users(monkeypatch: pytest.MonkeyPatch) -> None:
    settings = merge_settings()
    monkeypatch.setattr(account_merge, "get_settings", lambda: settings)
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    with TestClient(main.app) as client:
        _, source_id, _, _ = create_pair(phone, settings, with_files=False)
        outsider_token = create_outsider_session()
        challenge_id = request_challenge(client, phone)
        response = client.post(
            "/v1/auth/account-merges",
            json=merge_payload(phone, challenge_id, f"merge-{uuid.uuid4().hex}"),
            headers={"Authorization": f"Bearer {outsider_token}"},
        )
        assert response.status_code == 409
        assert response.json()["detail"] == "account_merge_conflict"

    with SessionLocal() as db:
        source = db.get(User, source_id)
        assert source is not None and source.status == UserStatus.active
        assert (
            db.scalar(
                select(AccountMergeAudit).where(AccountMergeAudit.source_user_id == source_id)
            )
            is None
        )


def test_file_copy_failure_rolls_back_database_and_copies(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    settings = merge_settings()
    monkeypatch.setattr(account_merge, "get_settings", lambda: settings)
    phone = f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}"
    original_copy = account_merge._copy_verified_file
    calls = 0

    def fail_second_copy(source: Path, destination: Path, *, expected_sha256: str | None) -> bool:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise AccountMergeError("simulated_copy_failure", status_code=500)
        return original_copy(source, destination, expected_sha256=expected_sha256)

    monkeypatch.setattr(account_merge, "_copy_verified_file", fail_second_copy)
    with TestClient(main.app) as client:
        canonical_id, source_id, token, source_paths = create_pair(phone, settings)
        challenge_id = request_challenge(client, phone)
        response = client.post(
            "/v1/auth/account-merges",
            json=merge_payload(phone, challenge_id, f"merge-{uuid.uuid4().hex}"),
            headers={"Authorization": f"Bearer {token}"},
        )
        assert response.status_code == 500
        assert response.json()["detail"] == "simulated_copy_failure"

    with SessionLocal() as db:
        source = db.get(User, source_id)
        assert source is not None and source.status == UserStatus.active
        page = db.scalar(select(ScanPage).where(ScanPage.owner_user_id == source_id))
        assert page is not None and page.original_path.startswith(f"users/{source_id}/")
        assert (
            db.scalar(
                select(AccountMergeAudit).where(AccountMergeAudit.source_user_id == source_id)
            )
            is None
        )
    for source_path in source_paths:
        assert source_path.is_file()
        relative = source_path.relative_to(main.settings.storage_root)
        canonical_path = main.settings.storage_root / Path(
            "users", canonical_id, *relative.parts[2:]
        )
        assert not canonical_path.exists()
