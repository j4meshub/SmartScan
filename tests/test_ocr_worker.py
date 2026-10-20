from __future__ import annotations

import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import AuditLog, JobStatus, ProcessingJob, Role, ScanPage, User
from services.worker.app.main import process
from services.worker.app.ocr import OcrEngine, OcrLine


class WorkerOcrEngine:
    model_version = "test-ocr-v1"

    def __init__(self, *, with_title: bool = True):
        self.call_index = 0
        self.with_title = with_title

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        del image
        self.call_index += 1
        if not self.with_title:
            return []
        if self.call_index == 2:
            return [
                OcrLine("13800138000", 0.99, (10, 5, 220, 35)),
                OcrLine("季度项目报告", 0.97, (10, 45, 240, 90)),
                OcrLine("工作内容", 0.94, (10, 180, 200, 215)),
            ]
        return [OcrLine("低置信旋转", 0.56, (10, 10, 40, 180))]


class FailingOcrEngine:
    model_version = "test-failure-v1"

    def recognize(self, image: Image.Image) -> list[OcrLine]:
        del image
        raise RuntimeError("不得写入持久错误的内部细节")


def register(
    client: TestClient,
    prefix: str,
    *,
    locale: str = "zh-CN",
) -> tuple[dict[str, str], str]:
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
            "locale": locale,
        },
    )
    assert response.status_code == 201, response.text
    return {"Authorization": f"Bearer {response.json()['access_token']}"}, username


def create_and_process(
    client: TestClient,
    headers: dict[str, str],
    engine: OcrEngine,
) -> tuple[str, str]:
    project = client.post(
        "/v1/projects",
        json={"title": "未命名扫描", "mode": "document", "reading_order": "ltr"},
        headers=headers,
    )
    assert project.status_code == 201
    image = Image.new("RGB", (800, 1200), "white")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    uploaded = client.post(
        f"/v1/projects/{project.json()['id']}/pages",
        files={"file": ("page.jpg", buffer.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert uploaded.status_code == 202, uploaded.text
    page_id = uploaded.json()["id"]
    with SessionLocal() as db:
        job_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.page_id == page_id))
        assert job_id is not None
        claim = claim_job_by_id(db, job_id, worker_id="ocr-test")
        assert claim is not None
        db.commit()
    process(claim, ocr_engine=engine)
    return project.json()["id"], page_id


def test_worker_saves_versioned_ocr_rotates_and_filters_suggested_name() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "ocr_owner")
        attacker_headers, _ = register(client, "ocr_attacker")
        admin_headers, admin_name = register(client, "ocr_admin")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            owner = db.scalar(select(User).where(User.username == owner_name))
            assert admin is not None and owner is not None
            owner_id = owner.id
            admin.role = Role.admin
            db.commit()

        project_id, page_id = create_and_process(client, owner_headers, WorkerOcrEngine())
        page = client.get(f"/v1/pages/{page_id}", headers=owner_headers)
        assert page.status_code == 200
        body = page.json()
        assert body["rotation_degrees"] == 90
        assert body["active_result"]["rotation_degrees"] == 90
        assert body["active_result"]["processor_version"] == "baseline-v2"
        assert body["ocr_status"] == "ready"
        assert body["ocr_result_version"] == body["active_result_version"] == 1
        assert body["ocr_model_version"] == "test-ocr-v1"
        assert body["ocr_rotation_degrees"] == 90
        assert body["ocr_title_candidate"] == "季度项目报告"
        assert "13800138000" in body["ocr_text"]
        assert len(body["ocr_details"]["passes"]) == 4

        project = client.get(f"/v1/projects/{project_id}", headers=owner_headers)
        assert project.json()["suggested_name"] == "季度项目报告"
        assert project.json()["suggested_name_source"] == "ocr"
        assert "13800138000" not in project.json()["suggested_name"]

        assert client.get(f"/v1/pages/{page_id}", headers=attacker_headers).status_code == 404
        assert client.get(f"/v1/pages/{page_id}", headers=admin_headers).status_code == 200
        with SessionLocal() as db:
            audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "view_page",
                    AuditLog.object_id == page_id,
                    AuditLog.target_user_id == owner_id,
                )
            )
            assert audit is not None and audit.result == "allowed"

        rotated = client.post(
            f"/v1/pages/{page_id}/rotations",
            json={"degrees": 90},
            headers=owner_headers,
        )
        assert rotated.status_code == 200
        assert rotated.json()["ocr_status"] == "stale"
        assert rotated.json()["ocr_text"] is None
        assert rotated.json()["ocr_result_version"] is None
        with SessionLocal() as db:
            stored = db.get(ScanPage, page_id)
            assert stored is not None and stored.ocr_details is None


def test_worker_uses_english_fallback_when_ocr_has_no_trusted_title() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ocr_fallback", locale="en")
        project_id, page_id = create_and_process(
            client,
            headers,
            WorkerOcrEngine(with_title=False),
        )

        page = client.get(f"/v1/pages/{page_id}", headers=headers)
        assert page.json()["ocr_status"] == "ready"
        assert page.json()["ocr_text"] == ""
        project = client.get(f"/v1/projects/{project_id}", headers=headers)
        assert project.json()["suggested_name"].startswith("SmartScan_")
        assert project.json()["suggested_name_source"] == "fallback"


def test_ocr_failure_keeps_original_and_enters_retryable_job_state() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ocr_failure")
        _, page_id = create_and_process(client, headers, FailingOcrEngine())

        with SessionLocal() as db:
            page = db.get(ScanPage, page_id)
            job = db.scalar(select(ProcessingJob).where(ProcessingJob.page_id == page_id))
            assert page is not None and job is not None
            assert page.active_result_version == 0
            assert page.processed_path is None
            assert (main.settings.storage_root / page.original_path).is_file()
            assert job.status == JobStatus.failed_retryable
            assert job.error_code == "baseline_processing_failed"
            assert job.error == "RuntimeError"
            assert "内部细节" not in job.error
