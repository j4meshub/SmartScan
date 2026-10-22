from __future__ import annotations

import io
import json
import uuid
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import select

from services.api.app import main
from services.api.app.ai_business import AI_CONSENT_VERSION
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id, claim_next_job
from services.api.app.models import (
    AiEnhancementTask,
    AiProviderCall,
    AuditLog,
    ProcessingJob,
    Role,
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


def create_processed_page(
    client: TestClient, headers: dict[str, str], *, mode: str = "document"
) -> tuple[str, str]:
    project = client.post(
        "/v1/projects",
        json={"title": "AI 业务编排", "mode": mode, "reading_order": "ltr"},
        headers=headers,
    )
    assert project.status_code == 201, project.text
    image = Image.new("RGB", (640, 480), "white")
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
        claim = claim_job_by_id(db, job_id, worker_id="ai-business-test")
        assert claim is not None
        db.commit()
    process(claim)
    return project.json()["id"], page_id


def enable_ai(client: TestClient, headers: dict[str, str], project_id: str) -> None:
    response = client.put(
        f"/v1/projects/{project_id}/ai-settings",
        json={"enabled": True, "consent_version": AI_CONSENT_VERSION},
        headers=headers,
    )
    assert response.status_code == 200, response.text
    assert response.json()["ai_enabled"] is True
    assert response.json()["ai_consent_version"] == AI_CONSENT_VERSION


def create_enhancement(
    client: TestClient,
    headers: dict[str, str],
    page_id: str,
    key: str,
    *,
    kind: str = "recommended",
) -> dict[str, object]:
    response = client.post(
        f"/v1/pages/{page_id}/ai-enhancements",
        json={"enhancement_kind": kind, "source_result_version": 1},
        headers={**headers, "Idempotency-Key": key},
    )
    assert response.status_code == 202, response.text
    return response.json()


def test_project_consent_idempotency_and_worker_isolation() -> None:
    with TestClient(main.app) as client:
        owner_headers, _ = register(client, "ai_owner")
        attacker_headers, _ = register(client, "ai_attacker")
        admin_headers, admin_name = register(client, "ai_admin")
        super_headers, super_name = register(client, "ai_super")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            super_admin = db.scalar(select(User).where(User.username == super_name))
            assert admin is not None and super_admin is not None
            admin.role = Role.admin
            super_admin.role = Role.super_admin
            db.commit()
        project_id, page_id = create_processed_page(client, owner_headers)

        capabilities = client.get("/v1/ai/capabilities", headers=owner_headers)
        assert capabilities.status_code == 200
        assert capabilities.json()["available"] is False
        assert capabilities.json()["business_orchestration_ready"] is True
        assert "detect_orientation" in capabilities.json()["task_types"]

        no_consent = client.post(
            f"/v1/pages/{page_id}/ai-enhancements",
            json={"enhancement_kind": "recommended", "source_result_version": 1},
            headers={**owner_headers, "Idempotency-Key": "ai-before-consent-0001"},
        )
        assert no_consent.status_code == 409
        with SessionLocal() as db:
            assert db.scalar(select(AiEnhancementTask.id)) is None

        wrong_consent = client.put(
            f"/v1/projects/{project_id}/ai-settings",
            json={"enabled": True, "consent_version": "outdated"},
            headers=owner_headers,
        )
        assert wrong_consent.status_code == 422
        enable_ai(client, owner_headers, project_id)

        task = create_enhancement(client, owner_headers, page_id, "ai-recommended-idempotency-0001")
        assert task["status"] == "queued"
        assert task["source_result_version"] == 1
        assert task["requested_tasks"] == [
            "classify_page",
            "detect_orientation",
            "extract_title",
        ]
        replay = create_enhancement(
            client, owner_headers, page_id, "ai-recommended-idempotency-0001"
        )
        assert replay["id"] == task["id"]
        assert replay["processing_job_id"] == task["processing_job_id"]
        conflict = client.post(
            f"/v1/pages/{page_id}/ai-enhancements",
            json={"enhancement_kind": "complex_ocr", "source_result_version": 1},
            headers={**owner_headers, "Idempotency-Key": "ai-recommended-idempotency-0001"},
        )
        assert conflict.status_code == 409
        assert conflict.json()["detail"] == "ai_idempotency_conflict"

        for staff_headers in (admin_headers, super_headers):
            staff_view = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=staff_headers)
            assert staff_view.status_code == 200
            assert staff_view.json()[0]["id"] == task["id"]
            staff_mutation = client.post(
                f"/v1/pages/{page_id}/ai-enhancements",
                json={"enhancement_kind": "recommended", "source_result_version": 1},
                headers={**staff_headers, "Idempotency-Key": uuid.uuid4().hex},
            )
            assert staff_mutation.status_code == 404

        assert (
            client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=attacker_headers).status_code
            == 404
        )
        denied = client.post(
            f"/v1/pages/{page_id}/ai-enhancements",
            json={"enhancement_kind": "recommended", "source_result_version": 1},
            headers={**attacker_headers, "Idempotency-Key": "ai-cross-user-denied-0001"},
        )
        assert denied.status_code == 404
        with SessionLocal() as db:
            assert (
                claim_job_by_id(
                    db,
                    str(task["processing_job_id"]),
                    worker_id="legacy-worker-must-not-claim",
                )
                is None
            )
            unrelated_claim = claim_next_job(db, worker_id="legacy-worker-must-not-claim")
            if unrelated_claim is not None:
                claimed_job = db.get(ProcessingJob, unrelated_claim.job_id)
                assert claimed_job is not None
                assert claimed_job.kind != "ai_enhancement"
                db.rollback()
            denied_audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "create_ai_enhancement",
                    AuditLog.object_id == page_id,
                    AuditLog.result == "denied",
                )
            )
            assert denied_audit is not None
            denied_view_audit = db.scalar(
                select(AuditLog).where(
                    AuditLog.action == "view_ai_enhancements",
                    AuditLog.object_id == page_id,
                    AuditLog.result == "denied",
                )
            )
            assert denied_view_audit is not None

        canceled = client.post(
            f"/v1/jobs/{task['processing_job_id']}/cancel", headers=owner_headers
        )
        assert canceled.status_code == 200
        listed = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=owner_headers)
        assert listed.status_code == 200
        assert listed.json()[0]["status"] == "canceled"

        with SessionLocal() as db:
            now = datetime.now(UTC)
            provider_call = AiProviderCall(
                enhancement_task_id=str(task["id"]),
                provider_id="mock",
                task_type="classify_page",
                status="succeeded",
                attempt_count=1,
                reserved_cost_microusd=0,
                charged_cost_microusd=0,
                request_body_bytes=0,
                response_body_bytes=0,
                started_at=now,
                lease_expires_at=now + timedelta(minutes=1),
                finished_at=now,
            )
            db.add(provider_call)
            db.commit()
            provider_call_id = provider_call.id

        deleted = client.delete(f"/v1/projects/{project_id}", headers=owner_headers)
        assert deleted.status_code == 202, deleted.text
        with SessionLocal() as db:
            assert db.get(AiEnhancementTask, str(task["id"])) is None
            aggregate = db.get(AiProviderCall, provider_call_id)
            assert aggregate is not None
            assert aggregate.enhancement_task_id is None


def test_candidate_acceptance_rejection_and_source_version_conflict() -> None:
    with TestClient(main.app) as client:
        headers, username = register(client, "ai_candidate")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)

        accepted = create_enhancement(client, headers, page_id, "ai-candidate-accept-0001")
        rejected = create_enhancement(client, headers, page_id, "ai-candidate-reject-0001")
        stale = create_enhancement(client, headers, page_id, "ai-candidate-stale-0001")
        with SessionLocal() as db:
            user = db.scalar(select(User).where(User.username == username))
            assert user is not None
            for task_id in (accepted["id"], rejected["id"], stale["id"]):
                task = db.get(AiEnhancementTask, task_id)
                assert task is not None
                task.status = "candidate_ready"
                task.candidate_result = json.dumps({"title": "候选标题"}, ensure_ascii=False)
                task.evidence = json.dumps(
                    {"source": "mock", "model_version": "mock-v1"}, ensure_ascii=False
                )
                task.provider_id = "mock"
                task.model = "mock-v1"
                task.confidence = 0.9
            db.commit()

        accept_response = client.post(
            f"/v1/ai-enhancements/{accepted['id']}/accept", headers=headers
        )
        assert accept_response.status_code == 200, accept_response.text
        assert accept_response.json()["status"] == "accepted"
        assert accept_response.json()["accepted_by_user_id"] is not None

        reject_response = client.post(
            f"/v1/ai-enhancements/{rejected['id']}/reject", headers=headers
        )
        assert reject_response.status_code == 200, reject_response.text
        assert reject_response.json()["status"] == "rejected"

        rotated = client.post(
            f"/v1/pages/{page_id}/rotations", json={"degrees": 90}, headers=headers
        )
        assert rotated.status_code == 200, rotated.text
        assert rotated.json()["active_result_version"] == 2
        stale_response = client.post(f"/v1/ai-enhancements/{stale['id']}/accept", headers=headers)
        assert stale_response.status_code == 409
        assert stale_response.json()["detail"] == "ai_source_version_conflict"
        listed = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=headers)
        by_id = {item["id"]: item for item in listed.json()}
        assert by_id[str(stale["id"])]["status"] == "stale"
        assert by_id[str(accepted["id"])]["status"] == "accepted"
        assert by_id[str(rejected["id"])]["status"] == "rejected"
