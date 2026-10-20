from __future__ import annotations

import hashlib
import io
import uuid
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main, project_cleanup
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.file_delivery import attachment_response
from services.api.app.models import (
    AuditLog,
    ExportArtifact,
    ProcessingJob,
    ProjectDeletion,
    ScanExport,
    ScanPage,
    ScanProject,
    UploadChunk,
    UploadSession,
)
from services.api.app.project_cleanup import process_next_project_cleanup


def register(client: TestClient, prefix: str) -> dict[str, str]:
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"{prefix}_{uuid.uuid4().hex[:10]}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def jpeg_bytes() -> bytes:
    image = Image.new("RGB", (800, 1000), "white")
    output = io.BytesIO()
    image.save(output, "JPEG")
    return output.getvalue()


def test_project_deletion_removes_database_resources_and_files() -> None:
    with TestClient(main.app) as client:
        owner_headers = register(client, "project_delete_owner")
        other_headers = register(client, "project_delete_other")
        project = client.post(
            "/v1/projects",
            json={"title": "待清理项目", "mode": "document", "reading_order": "ltr"},
            headers=owner_headers,
        )
        project_id = project.json()["id"]
        page = client.post(
            f"/v1/projects/{project_id}/pages",
            files={"file": ("page.jpg", jpeg_bytes(), "image/jpeg")},
            headers=owner_headers,
        )
        assert page.status_code == 202, page.text
        page_id = page.json()["id"]
        pending = jpeg_bytes()
        upload = client.post(
            "/v1/uploads",
            json={
                "project_id": project_id,
                "file_name": "pending.jpg",
                "mime_type": "image/jpeg",
                "size_bytes": len(pending),
                "sha256": hashlib.sha256(pending).hexdigest(),
                "idempotency_key": f"cleanup-{uuid.uuid4().hex}",
            },
            headers=owner_headers,
        )
        upload_id = upload.json()["id"]
        chunk = client.put(
            f"/v1/uploads/{upload_id}/chunks/0",
            content=pending,
            headers={
                **owner_headers,
                "X-Chunk-Sha256": hashlib.sha256(pending).hexdigest(),
            },
        )
        assert chunk.status_code == 200, chunk.text
        with SessionLocal() as db:
            page_row = db.get(ScanPage, page_id)
            chunk_row = db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id))
            assert page_row is not None and chunk_row is not None
            original_path = main.settings.storage_root / page_row.original_path
            chunk_path = main.settings.storage_root / chunk_row.relative_path
            assert original_path.is_file() and chunk_path.is_file()

        denied = client.delete(f"/v1/projects/{project_id}", headers=other_headers)
        assert denied.status_code == 404
        deleted = client.delete(f"/v1/projects/{project_id}", headers=owner_headers)
        assert deleted.status_code == 202, deleted.text
        assert deleted.json()["status"] == "completed"
        assert deleted.json()["attempts"] == 1
        deletion_id = deleted.json()["id"]
        status = client.get(f"/v1/project-deletions/{deletion_id}", headers=owner_headers)
        assert status.status_code == 200
        assert status.json()["status"] == "completed"
        assert not original_path.exists()
        assert not chunk_path.exists()

    with SessionLocal() as db:
        assert db.get(ScanProject, project_id) is None
        assert db.get(ScanPage, page_id) is None
        assert db.get(UploadSession, upload_id) is None
        assert db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id)) is None
        assert (
            db.scalar(select(ProcessingJob).where(ProcessingJob.project_id == project_id)) is None
        )
        assert db.scalar(select(ScanExport).where(ScanExport.project_id == project_id)) is None
        assert (
            db.scalar(
                select(ExportArtifact).join(ScanExport).where(ScanExport.project_id == project_id)
            )
            is None
        )
        deletion = db.get(ProjectDeletion, deletion_id)
        assert deletion is not None and deletion.status.value == "completed"
        denied_audit = db.scalar(
            select(AuditLog).where(
                AuditLog.object_id == project_id,
                AuditLog.action == "delete_project",
                AuditLog.result == "denied",
            )
        )
        assert denied_audit is not None


def test_project_file_cleanup_failure_remains_retryable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    with TestClient(main.app) as client:
        headers = register(client, "project_retry")
        project = client.post(
            "/v1/projects",
            json={"title": "清理重试", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        project_id = project.json()["id"]
        page = client.post(
            f"/v1/projects/{project_id}/pages",
            files={"file": ("retry.jpg", jpeg_bytes(), "image/jpeg")},
            headers=headers,
        )
        with SessionLocal() as db:
            page_row = db.get(ScanPage, page.json()["id"])
            assert page_row is not None
            target = (main.settings.storage_root / page_row.original_path).resolve()
        original_unlink = Path.unlink
        failed_once = False

        def fail_target_once(path: Path, *args, **kwargs):
            nonlocal failed_once
            if path.resolve() == target and not failed_once:
                failed_once = True
                raise OSError("simulated cleanup failure")
            return original_unlink(path, *args, **kwargs)

        monkeypatch.setattr(project_cleanup.Path, "unlink", fail_target_once)
        deleted = client.delete(f"/v1/projects/{project_id}", headers=headers)
        assert deleted.status_code == 202, deleted.text
        assert deleted.json()["status"] == "cleanup_pending"
        assert deleted.json()["last_error"] == "project_file_cleanup_failed"
        assert target.is_file()
        deletion_id = deleted.json()["id"]

    monkeypatch.setattr(project_cleanup.Path, "unlink", original_unlink)
    with SessionLocal() as db:
        retried = process_next_project_cleanup(db, settings=main.settings)
        assert retried is not None and retried.id == deletion_id
        assert retried.status.value == "completed"
        assert retried.attempts == 2
    assert not target.exists()


def test_x_accel_response_uses_internal_encoded_path(tmp_path: Path) -> None:
    source = tmp_path / "users" / "user-1" / "exports" / "报告.pdf"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"pdf")
    settings = Settings(
        _env_file=None,
        storage_root=tmp_path,
        internal_file_send_prefix="/_smartscan_files/",
    )
    response = attachment_response(
        absolute=source,
        relative="users/user-1/exports/报告.pdf",
        media_type="application/pdf",
        file_name="报告.pdf",
        settings=settings,
        sha256="a" * 64,
    )
    assert response.status_code == 200
    assert response.body == b""
    assert response.headers["x-accel-redirect"] == (
        "/_smartscan_files/users/user-1/exports/%E6%8A%A5%E5%91%8A.pdf"
    )
    assert response.headers["content-disposition"].endswith(
        "filename*=utf-8''%E6%8A%A5%E5%91%8A.pdf"
    )
    assert response.headers["etag"] == f'"{"a" * 64}"'
