from __future__ import annotations

import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import AuditLog, ProcessingJob, Role, ScanPage, User
from services.worker.app.main import process


def register(client: TestClient, prefix: str) -> tuple[dict[str, str], str]:
    suffix = uuid.uuid4().hex[:10]
    phone_suffix = str(uuid.uuid4().int % 10_000_000).zfill(7)
    username = f"{prefix}_{suffix}"
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{phone_suffix}",
            "sms_code": main.settings.dev_sms_code,
            "username": username,
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, username


def jpeg_bytes(width: int = 640, height: int = 480) -> bytes:
    image = Image.new("RGB", (width, height), "white")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    return buffer.getvalue()


def create_processed_page(
    client: TestClient,
    headers: dict[str, str],
) -> tuple[str, bytes]:
    project = client.post(
        "/v1/projects",
        json={"title": "页面版本", "mode": "document", "reading_order": "ltr"},
        headers=headers,
    )
    assert project.status_code == 201
    original = jpeg_bytes()
    uploaded = client.post(
        f"/v1/projects/{project.json()['id']}/pages",
        files={"file": ("page.jpg", original, "image/jpeg")},
        headers=headers,
    )
    assert uploaded.status_code == 202, uploaded.text
    page_id = uploaded.json()["id"]
    with SessionLocal() as db:
        job_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.page_id == page_id))
        assert job_id is not None
        claim = claim_job_by_id(db, job_id, worker_id="page-version-test")
        assert claim is not None
        db.commit()
    process(claim)
    return page_id, original


def test_processing_creates_version_and_review_without_blocking_job() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "page_owner")
        page_id, original = create_processed_page(client, headers)

        page = client.get(f"/v1/pages/{page_id}", headers=headers)
        assert page.status_code == 200
        body = page.json()
        assert body["active_result_version"] == 1
        assert body["active_result"]["result_type"] == "baseline"
        assert body["active_result"]["processor_version"] == "baseline-v1"
        assert body["quality_score"] < 100
        assert body["quality_details"]["width"] == 640
        assert body["review_status"] == "pending"
        assert body["review_reason"] in {"low_resolution", "low_contrast"}

        jobs = client.get("/v1/jobs", headers=headers)
        assert jobs.status_code == 200
        matching = [job for job in jobs.json() if job["page_id"] == page_id]
        assert matching[0]["status"] == "ready"

        original_response = client.get(
            f"/v1/pages/{page_id}/content?variant=original", headers=headers
        )
        assert original_response.status_code == 200
        assert original_response.content == original
        result_response = client.get(f"/v1/pages/{page_id}/content?version=1", headers=headers)
        assert result_response.status_code == 200
        assert result_response.content != original

        with SessionLocal() as db:
            stored = db.get(ScanPage, page_id)
            assert stored is not None
            original_path = main.settings.storage_root / stored.original_path
            result_path = main.settings.storage_root / stored.processed_path
            assert original_path.read_bytes() == original
            assert result_path != original_path


def test_manual_rotation_adds_immutable_version_and_review_can_be_confirmed() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "page_rotate")
        page_id, original = create_processed_page(client, headers)

        rotated = client.post(
            f"/v1/pages/{page_id}/rotations",
            json={"degrees": 90},
            headers=headers,
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["active_result_version"] == 2
        assert rotated.json()["rotation_degrees"] == 90
        assert rotated.json()["active_result"]["result_type"] == "manual_rotation"

        results = client.get(f"/v1/pages/{page_id}/results", headers=headers)
        assert results.status_code == 200
        assert [item["version"] for item in results.json()] == [1, 2]
        assert [item["rotation_degrees"] for item in results.json()] == [0, 90]
        assert (
            client.get(f"/v1/pages/{page_id}/content?version=1", headers=headers).content
            != client.get(f"/v1/pages/{page_id}/content?version=2", headers=headers).content
        )
        assert (
            client.get(f"/v1/pages/{page_id}/content?variant=original", headers=headers).content
            == original
        )

        confirmed = client.patch(
            f"/v1/pages/{page_id}/review",
            json={"status": "confirmed", "note": "用户已检查旋转与清晰度"},
            headers=headers,
        )
        assert confirmed.status_code == 200
        assert confirmed.json()["review_status"] == "confirmed"
        assert confirmed.json()["reviewed_by_user_id"] is not None
        assert confirmed.json()["review_reason"] == "用户已检查旋转与清晰度"


def test_page_result_mutations_are_owner_only_and_reads_follow_role_matrix() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "page_matrix_owner")
        attacker_headers, _ = register(client, "page_matrix_attacker")
        admin_headers, admin_name = register(client, "page_matrix_admin")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            owner = db.scalar(select(User).where(User.username == owner_name))
            assert admin is not None and owner is not None
            admin.role = Role.admin
            owner_id = owner.id
            db.commit()
        page_id, _ = create_processed_page(client, owner_headers)

        for headers in (attacker_headers,):
            assert client.get(f"/v1/pages/{page_id}", headers=headers).status_code == 404
            assert client.get(f"/v1/pages/{page_id}/results", headers=headers).status_code == 404
            assert (
                client.get(f"/v1/pages/{page_id}/content?version=1", headers=headers).status_code
                == 404
            )
        for headers in (attacker_headers, admin_headers):
            assert (
                client.post(
                    f"/v1/pages/{page_id}/rotations",
                    json={"degrees": 90},
                    headers=headers,
                ).status_code
                == 404
            )
            assert (
                client.patch(
                    f"/v1/pages/{page_id}/review",
                    json={"status": "confirmed"},
                    headers=headers,
                ).status_code
                == 404
            )

        assert client.get(f"/v1/pages/{page_id}", headers=admin_headers).status_code == 200
        assert client.get(f"/v1/pages/{page_id}/results", headers=admin_headers).status_code == 200
        with SessionLocal() as db:
            denied = db.scalars(
                select(AuditLog).where(
                    AuditLog.object_id == page_id,
                    AuditLog.result == "denied",
                )
            ).all()
        assert {item.action for item in denied} == {"rotate_page", "change_page_review"}
        assert {item.target_user_id for item in denied} == {owner_id}
