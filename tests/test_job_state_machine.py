from __future__ import annotations

import io
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import func, select

from services.api.app import main
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.job_service import (
    claim_job_by_id,
    heartbeat_job,
    mark_job_failure,
)
from services.api.app.migrations import upgrade_database
from services.api.app.models import (
    AuditLog,
    JobStatus,
    PageResult,
    ProcessingJob,
    Role,
    ScanProject,
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


def create_job() -> str:
    upgrade_database(main.settings.database_url)
    suffix = uuid.uuid4().hex
    with SessionLocal() as db:
        user = User(
            username=f"job_{suffix[:12]}",
            password_hash="hash",
            phone_hmac=suffix.ljust(64, "0"),
            phone_masked="+15****0014",
        )
        db.add(user)
        db.flush()
        project = ScanProject(owner_user_id=user.id, title="任务状态机")
        db.add(project)
        db.flush()
        job = ProcessingJob(
            owner_user_id=user.id,
            project_id=project.id,
            kind="document",
            max_attempts=3,
        )
        db.add(job)
        db.commit()
        return job.id


def upload_page(client: TestClient, headers: dict[str, str]) -> tuple[str, str]:
    project = client.post(
        "/v1/projects",
        json={"title": "任务恢复", "mode": "document", "reading_order": "ltr"},
        headers=headers,
    )
    image = Image.new("RGB", (640, 480), "white")
    buffer = io.BytesIO()
    image.save(buffer, "JPEG")
    page = client.post(
        f"/v1/projects/{project.json()['id']}/pages",
        files={"file": ("page.jpg", buffer.getvalue(), "image/jpeg")},
        headers=headers,
    )
    assert page.status_code == 202
    with SessionLocal() as db:
        job_id = db.scalar(
            select(ProcessingJob.id).where(ProcessingJob.page_id == page.json()["id"])
        )
        assert job_id is not None
    return page.json()["id"], job_id


def test_lease_recovery_rejects_stale_worker_and_escalates_failures() -> None:
    job_id = create_job()
    now = datetime.now(UTC)
    settings = Settings(
        _env_file=None,
        job_lease_seconds=30,
        job_retry_base_seconds=5,
        job_max_attempts=3,
    )
    with SessionLocal() as db:
        first = claim_job_by_id(
            db,
            job_id,
            worker_id="worker-a",
            now=now,
            settings=settings,
        )
        assert first is not None
        assert heartbeat_job(
            db,
            first,
            progress=40,
            now=now + timedelta(seconds=5),
            settings=settings,
        )
        db.commit()

    with SessionLocal() as db:
        assert (
            claim_job_by_id(
                db,
                job_id,
                worker_id="worker-b",
                now=now + timedelta(seconds=20),
                settings=settings,
            )
            is None
        )
        second = claim_job_by_id(
            db,
            job_id,
            worker_id="worker-b",
            now=now + timedelta(seconds=40),
            settings=settings,
        )
        assert second is not None and second.lease_token != first.lease_token
        assert not heartbeat_job(
            db,
            first,
            progress=80,
            now=now + timedelta(seconds=41),
            settings=settings,
        )
        failed = mark_job_failure(
            db,
            second,
            error_code="test_failure",
            error="可重试测试失败",
            now=now + timedelta(seconds=42),
            settings=settings,
        )
        assert failed is not None and failed.status == JobStatus.failed_retryable
        assert failed.available_at == now + timedelta(seconds=52)
        db.commit()

    with SessionLocal() as db:
        third = claim_job_by_id(
            db,
            job_id,
            worker_id="worker-c",
            now=now + timedelta(seconds=52),
            settings=settings,
        )
        assert third is not None
        final = mark_job_failure(
            db,
            third,
            error_code="test_failure",
            error="最终测试失败",
            now=now + timedelta(seconds=53),
            settings=settings,
        )
        assert final is not None and final.status == JobStatus.failed_final
        assert final.completed_at is not None
        db.commit()


def test_expired_lease_recovery_creates_one_result_and_stale_claim_cannot_commit() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "job_recovery")
        page_id, job_id = upload_page(client, headers)
        now = datetime.now(UTC)
        with SessionLocal() as db:
            first = claim_job_by_id(db, job_id, worker_id="crashed", now=now)
            assert first is not None
            db.commit()
        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            assert job is not None
            job.lease_until = now - timedelta(seconds=1)
            db.commit()
        with SessionLocal() as db:
            recovered = claim_job_by_id(
                db,
                job_id,
                worker_id="recovered",
                now=now + timedelta(seconds=1),
            )
            assert recovered is not None
            db.commit()

        process(first)
        process(recovered)
        process(recovered)

        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            result_count = db.scalar(
                select(func.count()).select_from(PageResult).where(PageResult.page_id == page_id)
            )
            assert job is not None and job.status == JobStatus.ready
            assert job.result_version == 1
            assert job.attempts == 2
            assert result_count == 1


def test_job_detail_cancel_retry_and_idor_matrix() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "job_owner")
        attacker_headers, _ = register(client, "job_attacker")
        admin_headers, admin_name = register(client, "job_admin")
        with SessionLocal() as db:
            owner = db.scalar(select(User).where(User.username == owner_name))
            admin = db.scalar(select(User).where(User.username == admin_name))
            assert owner is not None and admin is not None
            owner_id = owner.id
            admin.role = Role.admin
            db.commit()
        page_id, job_id = upload_page(client, owner_headers)

        detail = client.get(f"/v1/jobs/{job_id}", headers=owner_headers)
        assert detail.status_code == 200
        assert detail.json()["status"] == "queued"
        assert detail.json()["progress"] == 0
        assert "lease_token" not in detail.json()

        assert client.get(f"/v1/jobs/{job_id}", headers=attacker_headers).status_code == 404
        assert client.get(f"/v1/jobs/{job_id}", headers=admin_headers).status_code == 200
        for headers in (attacker_headers, admin_headers):
            assert client.post(f"/v1/jobs/{job_id}/cancel", headers=headers).status_code == 404

        with SessionLocal() as db:
            active_claim = claim_job_by_id(db, job_id, worker_id="cancel-test")
            assert active_claim is not None
            db.commit()
        canceled = client.post(f"/v1/jobs/{job_id}/cancel", headers=owner_headers)
        assert canceled.status_code == 200
        assert canceled.json()["status"] == "canceled"
        assert canceled.json()["canceled_at"] is not None
        process(active_claim)
        with SessionLocal() as db:
            result_count = db.scalar(
                select(func.count()).select_from(PageResult).where(PageResult.page_id == page_id)
            )
            assert result_count == 0
        assert client.post(f"/v1/jobs/{job_id}/retry", headers=owner_headers).status_code == 409

        with SessionLocal() as db:
            job = db.get(ProcessingJob, job_id)
            assert job is not None
            job.status = JobStatus.failed_final
            job.attempts = job.max_attempts
            db.commit()
        retried = client.post(f"/v1/jobs/{job_id}/retry", headers=owner_headers)
        assert retried.status_code == 200
        assert retried.json()["status"] == "queued"
        assert retried.json()["attempts"] == 0
        assert retried.json()["cancel_requested_at"] is None
        assert retried.json()["canceled_at"] is None

        with SessionLocal() as db:
            denied = db.scalars(
                select(AuditLog).where(
                    AuditLog.object_id == job_id,
                    AuditLog.result == "denied",
                )
            ).all()
        assert {item.action for item in denied} == {"cancel_job"}
        assert {item.target_user_id for item in denied} == {owner_id}
