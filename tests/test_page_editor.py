from __future__ import annotations

import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import AuditLog, ProcessingJob
from services.worker.app.main import process


def register(client: TestClient, prefix: str) -> dict[str, str]:
    suffix = uuid.uuid4().hex[:10]
    response = client.post(
        "/v1/auth/register",
        json={
            "phone": f"+1555{str(uuid.uuid4().int % 10_000_000).zfill(7)}",
            "sms_code": main.settings.dev_sms_code,
            "username": f"{prefix}_{suffix}",
            "password": "correct-horse-battery-staple",
            "locale": "zh-CN",
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


def jpeg_bytes(color: tuple[int, int, int], width: int = 800, height: int = 600) -> bytes:
    image = Image.new("RGB", (width, height), color)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def create_processed_page(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    color: tuple[int, int, int],
) -> tuple[str, bytes]:
    original = jpeg_bytes(color)
    response = client.post(
        f"/v1/projects/{project_id}/pages",
        files={"file": ("page.jpg", original, "image/jpeg")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    page_id = response.json()["id"]
    with SessionLocal() as db:
        job_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.page_id == page_id))
        assert job_id is not None
        claim = claim_job_by_id(db, job_id, worker_id="page-editor-test")
        assert claim is not None
        db.commit()
    process(claim)
    return page_id, original


def test_perspective_and_filter_create_immutable_page_version() -> None:
    with TestClient(main.app) as client:
        headers = register(client, "editor")
        project = client.post(
            "/v1/projects",
            json={"title": "页面编辑", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        ).json()
        page_id, original = create_processed_page(client, headers, project["id"], (190, 120, 70))

        edited = client.post(
            f"/v1/pages/{page_id}/edits",
            json={
                "corners": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                    {"x": 0.1, "y": 0.9},
                ],
                "filter": "grayscale",
            },
            headers=headers,
        )
        assert edited.status_code == 200, edited.text
        body = edited.json()
        assert body["active_result_version"] == 2
        assert body["active_result"]["result_type"] == "manual_edit"
        assert body["ocr_status"] == "stale"

        content = client.get(f"/v1/pages/{page_id}/content", headers=headers)
        with Image.open(io.BytesIO(content.content)) as result:
            assert result.width < 800
            assert result.height < 600
            red, green, blue = result.convert("RGB").getpixel((10, 10))
            assert red == green == blue
        original_response = client.get(
            f"/v1/pages/{page_id}/content?variant=original", headers=headers
        )
        assert original_response.content == original


def test_invalid_corners_and_empty_edit_are_rejected() -> None:
    with TestClient(main.app) as client:
        headers = register(client, "invalid_editor")
        project = client.post(
            "/v1/projects",
            json={"title": "无效四角", "mode": "document", "reading_order": "ltr"},
            headers=headers,
        ).json()
        page_id, _ = create_processed_page(client, headers, project["id"], (255, 255, 255))
        empty = client.post(
            f"/v1/pages/{page_id}/edits",
            json={"filter": "original"},
            headers=headers,
        )
        assert empty.status_code == 422
        crossed = client.post(
            f"/v1/pages/{page_id}/edits",
            json={
                "corners": [
                    {"x": 0.1, "y": 0.1},
                    {"x": 0.9, "y": 0.9},
                    {"x": 0.9, "y": 0.1},
                    {"x": 0.1, "y": 0.9},
                ],
                "filter": "bw",
            },
            headers=headers,
        )
        assert crossed.status_code == 422
        assert crossed.json()["detail"] == "page_corners_invalid"


def test_page_order_requires_exact_owner_page_set_and_is_audited() -> None:
    with TestClient(main.app) as client:
        owner = register(client, "order_owner")
        other = register(client, "order_other")
        project = client.post(
            "/v1/projects",
            json={"title": "页面顺序", "mode": "book", "reading_order": "ltr"},
            headers=owner,
        ).json()
        first, _ = create_processed_page(client, owner, project["id"], (255, 0, 0))
        second, _ = create_processed_page(client, owner, project["id"], (0, 0, 255))

        denied = client.patch(
            f"/v1/projects/{project['id']}/pages/order",
            json={"page_ids": [second, first]},
            headers=other,
        )
        assert denied.status_code == 404
        incomplete = client.patch(
            f"/v1/projects/{project['id']}/pages/order",
            json={"page_ids": [first]},
            headers=owner,
        )
        assert incomplete.status_code == 422
        duplicate = client.patch(
            f"/v1/projects/{project['id']}/pages/order",
            json={"page_ids": [first, first]},
            headers=owner,
        )
        assert duplicate.status_code == 422

        reordered = client.patch(
            f"/v1/projects/{project['id']}/pages/order",
            json={"page_ids": [second, first]},
            headers=owner,
        )
        assert reordered.status_code == 200, reordered.text
        assert [(item["id"], item["page_number"]) for item in reordered.json()] == [
            (second, 1),
            (first, 2),
        ]
        listed = client.get(f"/v1/projects/{project['id']}/pages", headers=owner)
        assert [item["id"] for item in listed.json()] == [second, first]

        with SessionLocal() as db:
            actions = set(
                db.scalars(select(AuditLog.action).where(AuditLog.object_id == project["id"]))
            )
        assert "reorder_pages" in actions


def test_page_edit_is_owner_only_and_denial_is_audited() -> None:
    with TestClient(main.app) as client:
        owner = register(client, "edit_owner")
        other = register(client, "edit_other")
        project = client.post(
            "/v1/projects",
            json={"title": "编辑隔离", "mode": "document", "reading_order": "ltr"},
            headers=owner,
        ).json()
        page_id, _ = create_processed_page(client, owner, project["id"], (120, 120, 120))
        denied = client.post(
            f"/v1/pages/{page_id}/edits",
            json={"filter": "enhance"},
            headers=other,
        )
        assert denied.status_code == 404
        with SessionLocal() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.object_id == page_id,
                    AuditLog.action == "edit_page",
                    AuditLog.result == "denied",
                )
            )
        assert audit is not None
