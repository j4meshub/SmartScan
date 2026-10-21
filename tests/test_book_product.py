from __future__ import annotations

import io
import json
import uuid

import numpy as np
from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import (
    AuditLog,
    JobStatus,
    ProcessingJob,
    Role,
    ScanExport,
    ScanPage,
    User,
)
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


def jpeg_bytes(image: Image.Image) -> bytes:
    payload = io.BytesIO()
    image.save(payload, "JPEG", quality=95)
    return payload.getvalue()


def spread_jpeg() -> bytes:
    width, height = 1400, 900
    spine = 610
    pixels = np.full((height, width, 3), 28, dtype=np.uint8)
    for x in range(90, spine - 12):
        normalized = (x - 90) / max(1, spine - 102 - 90)
        top = round(95 + 34 * (normalized - 0.45) ** 2)
        bottom = round(805 - 24 * (normalized - 0.45) ** 2)
        pixels[top:bottom, x] = (242, 241, 232)
    for x in range(spine + 12, 1320):
        normalized = (x - (spine + 12)) / max(1, 1320 - (spine + 12))
        top = round(105 + 40 * (normalized - 0.55) ** 2)
        bottom = round(795 - 30 * (normalized - 0.55) ** 2)
        pixels[top:bottom, x] = (239, 240, 232)
    image = Image.fromarray(pixels)
    draw = ImageDraw.Draw(image)
    for y in range(180, 740, 70):
        draw.line((150, y, spine - 75, y + 4), fill="black", width=4)
        draw.line((spine + 80, y + 3, 1240, y), fill="black", width=4)
    return jpeg_bytes(image)


def single_page_jpeg(color: tuple[int, int, int] = (242, 242, 238)) -> bytes:
    image = Image.new("RGB", (1000, 800), (25, 25, 25))
    draw = ImageDraw.Draw(image)
    draw.rectangle((120, 80, 880, 720), fill=color)
    for y in range(180, 650, 70):
        draw.line((220, y, 780, y), fill="black", width=4)
    return jpeg_bytes(image)


def create_book_project(
    client: TestClient,
    headers: dict[str, str],
    *,
    reading_order: str = "ltr",
) -> str:
    response = client.post(
        "/v1/projects",
        json={"title": "双页书籍", "mode": "book", "reading_order": reading_order},
        headers=headers,
    )
    assert response.status_code == 201, response.text
    return response.json()["id"]


def upload_page(
    client: TestClient,
    headers: dict[str, str],
    project_id: str,
    payload: bytes,
) -> str:
    response = client.post(
        f"/v1/projects/{project_id}/pages",
        files={"file": ("book.jpg", payload, "image/jpeg")},
        headers=headers,
    )
    assert response.status_code == 202, response.text
    return response.json()["id"]


def process_project_jobs(project_id: str) -> None:
    while True:
        with SessionLocal() as db:
            job_id = db.scalar(
                select(ProcessingJob.id)
                .where(
                    ProcessingJob.project_id == project_id,
                    ProcessingJob.status == JobStatus.queued,
                )
                .order_by(ProcessingJob.created_at, ProcessingJob.id)
            )
            if job_id is None:
                return
            claim = claim_job_by_id(db, job_id, worker_id="book-product-test")
            assert claim is not None
            db.commit()
        process(claim)
        with SessionLocal() as db:
            completed = db.get(ProcessingJob, job_id)
            assert completed is not None
            assert completed.status == JobStatus.ready, (
                completed.error_code,
                completed.error,
            )


def test_spread_creates_two_logical_pages_in_explicit_reading_order() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "book_ltr")
        project_id = create_book_project(client, headers)
        captured_page_id = upload_page(client, headers, project_id, spread_jpeg())

        process_project_jobs(project_id)

        response = client.get(f"/v1/projects/{project_id}/pages", headers=headers)
        assert response.status_code == 200
        pages = response.json()
        assert [page["book_side"] for page in pages] == ["left", "right"]
        assert [page["page_number"] for page in pages] == [1, 2]
        assert {page["book_capture_id"] for page in pages} == {captured_page_id}
        assert all(page["book_split_status"] == "split" for page in pages)
        assert all(page["book_split_confidence"] >= 0.5 for page in pages)
        assert all(page["active_result"]["result_type"] == "book_logical" for page in pages)

        with SessionLocal() as db:
            stored = list(
                db.scalars(
                    select(ScanPage)
                    .where(ScanPage.project_id == project_id)
                    .order_by(ScanPage.page_number)
                )
            )
            assert len({page.original_path for page in stored}) == 1
            assert len({page.book_logical_source_path for page in stored}) == 2
            assert all(page.book_logical_source_path for page in stored)
            for page in stored:
                assert (main.settings.storage_root / page.original_path).is_file()
                assert (main.settings.storage_root / page.book_logical_source_path).is_file()


def test_spread_uses_project_right_to_left_order_without_language_inference() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "book_rtl")
        project_id = create_book_project(client, headers, reading_order="rtl")
        upload_page(client, headers, project_id, spread_jpeg())

        process_project_jobs(project_id)

        pages = client.get(f"/v1/projects/{project_id}/pages", headers=headers).json()
        assert [page["book_side"] for page in pages] == ["right", "left"]


def test_uncertain_spread_keeps_one_page_and_requires_review() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "book_fallback")
        project_id = create_book_project(client, headers)
        upload_page(client, headers, project_id, single_page_jpeg())

        process_project_jobs(project_id)

        pages = client.get(f"/v1/projects/{project_id}/pages", headers=headers).json()
        assert len(pages) == 1
        page = pages[0]
        assert page["book_side"] == "single"
        assert page["book_split_status"] == "fallback"
        assert page["book_split_reason"] == "spine_not_confident"
        assert page["review_status"] == "pending"
        assert page["review_reason"] == "book_split_review"
        assert page["quality_details"]["book"]["split_status"] == "fallback"


def test_single_side_retake_replaces_only_target_and_default_export_uses_new_page() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "book_retake")
        project_id = create_book_project(client, headers)
        upload_page(client, headers, project_id, spread_jpeg())
        process_project_jobs(project_id)
        initial_pages = client.get(f"/v1/projects/{project_id}/pages", headers=headers).json()
        target = next(page for page in initial_pages if page["book_side"] == "left")
        untouched = next(page for page in initial_pages if page["book_side"] == "right")

        retake = client.post(
            f"/v1/pages/{target['id']}/book-retakes",
            files={"file": ("left-retake.jpg", single_page_jpeg((235, 240, 245)), "image/jpeg")},
            headers=headers,
        )
        assert retake.status_code == 202, retake.text
        replacement = retake.json()
        assert replacement["id"] != target["id"]
        assert replacement["page_number"] == target["page_number"]
        assert replacement["book_side"] == "left"
        assert replacement["book_split_status"] == "retake"
        assert replacement["book_is_current"] is True

        process_project_jobs(project_id)

        old_page = client.get(f"/v1/pages/{target['id']}", headers=headers).json()
        assert old_page["book_is_current"] is False
        assert old_page["book_replaced_by_page_id"] == replacement["id"]
        active_pages = client.get(f"/v1/projects/{project_id}/pages", headers=headers).json()
        assert {page["id"] for page in active_pages} == {replacement["id"], untouched["id"]}
        assert [page["book_side"] for page in active_pages] == ["left", "right"]
        assert all(page["active_result"] is not None for page in active_pages)

        repeated = client.post(
            f"/v1/pages/{target['id']}/book-retakes",
            files={"file": ("again.jpg", single_page_jpeg(), "image/jpeg")},
            headers=headers,
        )
        assert repeated.status_code == 409
        assert repeated.json() == {"detail": "book_page_already_replaced"}

        exported = client.post(
            f"/v1/projects/{project_id}/exports",
            json={"format": "jpg", "quality": "small", "include_ocr_text": False},
            headers=headers,
        )
        assert exported.status_code == 201, exported.text
        assert exported.json()["page_count"] == 2
        with SessionLocal() as db:
            stored_export = db.get(ScanExport, exported.json()["id"])
            assert stored_export is not None
            snapshot = json.loads(stored_export.page_snapshot)
            old_stored = db.get(ScanPage, target["id"])
            new_stored = db.get(ScanPage, replacement["id"])
            assert old_stored is not None and new_stored is not None
            assert old_stored.original_path != new_stored.original_path
            assert (main.settings.storage_root / old_stored.original_path).is_file()
            assert (main.settings.storage_root / new_stored.original_path).is_file()
        assert {item["page_id"] for item in snapshot} == {replacement["id"], untouched["id"]}


def test_book_retake_is_owner_only_for_user_and_admin_and_denials_are_audited() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "book_owner")
        attacker_headers, _ = register(client, "book_attacker")
        admin_headers, admin_name = register(client, "book_admin")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            owner = db.scalar(select(User).where(User.username == owner_name))
            assert admin is not None and owner is not None
            admin.role = Role.admin
            owner_id = owner.id
            db.commit()
        project_id = create_book_project(client, owner_headers)
        upload_page(client, owner_headers, project_id, spread_jpeg())
        process_project_jobs(project_id)
        target = client.get(f"/v1/projects/{project_id}/pages", headers=owner_headers).json()[0]

        for headers in (attacker_headers, admin_headers):
            response = client.post(
                f"/v1/pages/{target['id']}/book-retakes",
                files={"file": ("retake.jpg", single_page_jpeg(), "image/jpeg")},
                headers=headers,
            )
            assert response.status_code == 404

        with SessionLocal() as db:
            denials = list(
                db.scalars(
                    select(AuditLog).where(
                        AuditLog.action == "retake_book_side",
                        AuditLog.object_id == target["id"],
                        AuditLog.result == "denied",
                    )
                )
            )
        assert len(denials) == 2
        assert {item.target_user_id for item in denials} == {owner_id}


def test_project_cleanup_removes_shared_original_and_all_logical_sources() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "book_cleanup")
        project_id = create_book_project(client, headers)
        upload_page(client, headers, project_id, spread_jpeg())
        process_project_jobs(project_id)
        with SessionLocal() as db:
            pages = list(db.scalars(select(ScanPage).where(ScanPage.project_id == project_id)))
            original = main.settings.storage_root / pages[0].original_path
            logical_sources = [
                main.settings.storage_root / page.book_logical_source_path
                for page in pages
                if page.book_logical_source_path
            ]
        assert original.is_file()
        assert len(logical_sources) == 2
        assert all(path.is_file() for path in logical_sources)

        deleted = client.delete(f"/v1/projects/{project_id}", headers=headers)

        assert deleted.status_code == 202, deleted.text
        assert deleted.json()["status"] == "completed"
        assert not original.exists()
        assert all(not path.exists() for path in logical_sources)
