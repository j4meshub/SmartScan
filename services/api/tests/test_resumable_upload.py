import hashlib
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.models import AuditLog, UploadChunk, UploadSession
from services.api.app.upload_cleanup import process_next_upload_cleanup


def register(client: TestClient, prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    phone_suffix = str(uuid.uuid4().int % 10_000_000).zfill(7)
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{phone_suffix}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"{prefix}_{suffix}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def test_chunk_upload_resumes_is_isolated_and_completes_idempotently():
    original_chunk_size = main.settings.upload_chunk_bytes
    main.settings.upload_chunk_bytes = 1024
    try:
        with TestClient(main.app) as client:
            owner_headers = register(client, "owner")
            other_headers = register(client, "other")
            project = client.post(
                "/v1/projects",
                json={"title": "断点续传", "mode": "document", "reading_order": "ltr"},
                headers=owner_headers,
            )
            assert project.status_code == 201, project.text

            payload = b"\x89PNG\r\n\x1a\n" + b"smartscan" * 300
            digest = hashlib.sha256(payload).hexdigest()
            create_body = {
                "project_id": project.json()["id"],
                "file_name": "../page.png",
                "mime_type": "image/png",
                "size_bytes": len(payload),
                "sha256": digest,
                "idempotency_key": f"test-{uuid.uuid4().hex}",
            }
            initiated = client.post("/v1/uploads", json=create_body, headers=owner_headers)
            assert initiated.status_code == 201, initiated.text
            upload = initiated.json()
            assert upload["file_name"] == "page.png"
            assert upload["total_chunks"] == 3

            repeated = client.post("/v1/uploads", json=create_body, headers=owner_headers)
            assert repeated.status_code == 201
            assert repeated.json()["id"] == upload["id"]

            conflicting = client.post(
                "/v1/uploads",
                json={**create_body, "sha256": "0" * 64},
                headers=owner_headers,
            )
            assert conflicting.status_code == 409
            renamed = client.post(
                "/v1/uploads",
                json={**create_body, "file_name": "other-page.png"},
                headers=owner_headers,
            )
            assert renamed.status_code == 409

            first = payload[: upload["chunk_size"]]
            first_hash = hashlib.sha256(first).hexdigest()
            accepted = client.put(
                f"/v1/uploads/{upload['id']}/chunks/0",
                content=first,
                headers={**owner_headers, "X-Chunk-Sha256": first_hash},
            )
            assert accepted.status_code == 200, accepted.text

            status = client.get(f"/v1/uploads/{upload['id']}", headers=owner_headers)
            assert status.status_code == 200
            assert status.json()["received_chunks"] == [0]
            hidden = client.get(f"/v1/uploads/{upload['id']}", headers=other_headers)
            assert hidden.status_code == 404

            second = payload[upload["chunk_size"] : upload["chunk_size"] * 2]
            rejected = client.put(
                f"/v1/uploads/{upload['id']}/chunks/1",
                content=second,
                headers={**owner_headers, "X-Chunk-Sha256": "0" * 64},
            )
            assert rejected.status_code == 422

            for index in range(1, upload["total_chunks"]):
                start = index * upload["chunk_size"]
                chunk = payload[start : start + upload["chunk_size"]]
                response = client.put(
                    f"/v1/uploads/{upload['id']}/chunks/{index}",
                    content=chunk,
                    headers={
                        **owner_headers,
                        "X-Chunk-Sha256": hashlib.sha256(chunk).hexdigest(),
                    },
                )
                assert response.status_code == 200, response.text

            completed = client.post(f"/v1/uploads/{upload['id']}/complete", headers=owner_headers)
            assert completed.status_code == 202, completed.text
            completed_again = client.post(
                f"/v1/uploads/{upload['id']}/complete", headers=owner_headers
            )
            assert completed_again.status_code == 202
            assert completed_again.json()["id"] == completed.json()["id"]

            jobs = client.get("/v1/jobs", headers=owner_headers)
            matching_jobs = [job for job in jobs.json() if job["page_id"] == completed.json()["id"]]
            assert len(matching_jobs) == 1
    finally:
        main.settings.upload_chunk_bytes = original_chunk_size


def test_pending_upload_can_be_canceled_idempotently_and_removes_chunks():
    with TestClient(main.app) as client:
        owner_headers = register(client, "cancel_owner")
        other_headers = register(client, "cancel_other")
        project = client.post(
            "/v1/projects",
            json={"title": "取消上传", "mode": "document", "reading_order": "ltr"},
            headers=owner_headers,
        )
        payload = b"\x89PNG\r\n\x1a\n" + b"cancel-me" * 20
        initiated = client.post(
            "/v1/uploads",
            json={
                "project_id": project.json()["id"],
                "file_name": "cancel.png",
                "mime_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "idempotency_key": f"cancel-{uuid.uuid4().hex}",
            },
            headers=owner_headers,
        )
        upload_id = initiated.json()["id"]
        written = client.put(
            f"/v1/uploads/{upload_id}/chunks/0",
            content=payload,
            headers={
                **owner_headers,
                "X-Chunk-Sha256": hashlib.sha256(payload).hexdigest(),
            },
        )
        assert written.status_code == 200, written.text
        with SessionLocal() as db:
            chunk = db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id))
            assert chunk is not None
            chunk_path = main.settings.storage_root / chunk.relative_path
            assert chunk_path.is_file()

        assert client.delete(f"/v1/uploads/{upload_id}", headers=other_headers).status_code == 404
        assert client.delete(f"/v1/uploads/{upload_id}", headers=owner_headers).status_code == 204
        assert client.delete(f"/v1/uploads/{upload_id}", headers=owner_headers).status_code == 204
        status = client.get(f"/v1/uploads/{upload_id}", headers=owner_headers)
        assert status.status_code == 200
        assert status.json()["status"] == "canceled"
        assert status.json()["received_chunks"] == []
        assert not chunk_path.exists()
        assert (
            client.post(f"/v1/uploads/{upload_id}/complete", headers=owner_headers).status_code
            == 409
        )
        with SessionLocal() as db:
            denied_audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.object_id == upload_id,
                    AuditLog.action == "cancel_upload",
                    AuditLog.result == "denied",
                )
            )
            assert denied_audit is not None


def test_expired_upload_chunks_are_reclaimed_by_cleanup_queue():
    with TestClient(main.app) as client:
        headers = register(client, "expiry_cleanup")
        project = client.post(
            "/v1/projects",
            json={"title": "过期上传", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        )
        payload = b"\x89PNG\r\n\x1a\n" + b"expired" * 20
        upload = client.post(
            "/v1/uploads",
            json={
                "project_id": project.json()["id"],
                "file_name": "expired.png",
                "mime_type": "image/png",
                "size_bytes": len(payload),
                "sha256": hashlib.sha256(payload).hexdigest(),
                "idempotency_key": f"expired-{uuid.uuid4().hex}",
            },
            headers=headers,
        )
        upload_id = upload.json()["id"]
        assert (
            client.put(
                f"/v1/uploads/{upload_id}/chunks/0",
                content=payload,
                headers={
                    **headers,
                    "X-Chunk-Sha256": hashlib.sha256(payload).hexdigest(),
                },
            ).status_code
            == 200
        )

    with SessionLocal() as db:
        upload_row = db.get(UploadSession, upload_id)
        chunk = db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id))
        assert upload_row is not None and chunk is not None
        chunk_path = main.settings.storage_root / chunk.relative_path
        upload_row.expires_at = datetime.now(UTC) - timedelta(seconds=1)
        db.commit()
        cleaned = process_next_upload_cleanup(db, settings=main.settings)
        assert cleaned is not None and cleaned.id == upload_id
        assert cleaned.status.value == "expired"
        assert db.scalar(select(UploadChunk).where(UploadChunk.upload_id == upload_id)) is None
    assert not chunk_path.exists()
