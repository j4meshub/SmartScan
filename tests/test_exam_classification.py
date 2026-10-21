from __future__ import annotations

import io
import uuid

from fastapi.testclient import TestClient
from PIL import Image, ImageDraw
from sqlalchemy import select

from services.api.app import main
from services.api.app.database import SessionLocal
from services.api.app.job_service import claim_job_by_id
from services.api.app.models import AuditLog, ProcessingJob, Role, User
from services.worker.app.main import process


class FixedExamModel:
    model_version = "integration-exam-v1"

    def predict_exam_probability(self, image: Image.Image) -> float:
        del image
        return 0.95


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


def exam_jpeg() -> bytes:
    image = Image.new("RGB", (1200, 1600), "white")
    draw = ImageDraw.Draw(image)
    for row in range(12):
        y = 120 + row * 105
        for column in range(8):
            x = 120 + column * 90
            draw.rectangle((x, y, x + 35, y + 20), fill="black")
        draw.line((170, y + 55, 1020, y + 55), fill="black", width=3)
    for y in (180, 420, 660, 900):
        draw.rectangle((80, y, 105, y + 25), outline="black", width=3)
    buffer = io.BytesIO()
    image.save(buffer, "JPEG", quality=95)
    return buffer.getvalue()


def create_and_process_page(
    client: TestClient,
    headers: dict[str, str],
    *,
    mode: str = "document",
) -> str:
    project = client.post(
        "/v1/projects",
        json={"title": "试卷分类", "mode": mode, "reading_order": "ltr"},
        headers=headers,
    )
    assert project.status_code == 201
    uploaded = client.post(
        f"/v1/projects/{project.json()['id']}/pages",
        files={"file": ("exam.jpg", exam_jpeg(), "image/jpeg")},
        headers=headers,
    )
    assert uploaded.status_code == 202, uploaded.text
    page_id = uploaded.json()["id"]
    with SessionLocal() as db:
        job_id = db.scalar(select(ProcessingJob.id).where(ProcessingJob.page_id == page_id))
        assert job_id is not None
        claim = claim_job_by_id(db, job_id, worker_id="exam-classification-test")
        assert claim is not None
        db.commit()
    process(claim, exam_model=FixedExamModel())
    return page_id


def test_worker_persists_versioned_exam_classification_and_owner_can_dismiss() -> None:
    with TestClient(main.app) as client:
        owner_headers, _ = register(client, "exam_owner")
        page_id = create_and_process_page(client, owner_headers)

        page = client.get(f"/v1/pages/{page_id}", headers=owner_headers)
        assert page.status_code == 200
        body = page.json()
        assert body["exam_classification_status"] == "ready"
        assert body["exam_result_version"] == body["active_result_version"] == 1
        assert body["exam_classifier_version"] == "exam-fusion-v1:integration-exam-v1"
        assert body["exam_prediction"] == "exam"
        assert body["exam_probability"] >= 0.65
        assert body["exam_confidence_band"] == "high"
        assert body["exam_recommendation"] == "suggest_cleanup"
        assert body["exam_suggestion_visible"] is True
        assert body["exam_details"]["model_status"] == "ready"

        dismissed = client.put(
            f"/v1/pages/{page_id}/exam-suggestion-dismissal",
            json={"result_version": 1, "reason": "用户选择普通扫描"},
            headers=owner_headers,
        )
        assert dismissed.status_code == 200, dismissed.text
        dismissed_body = dismissed.json()
        assert dismissed_body["exam_suggestion_visible"] is False
        assert dismissed_body["exam_prediction"] == "exam"
        assert dismissed_body["exam_probability"] == body["exam_probability"]
        assert dismissed_body["exam_suggestion_dismissed_result_version"] == 1
        assert dismissed_body["exam_suggestion_dismissed_by_user_id"] is not None
        assert dismissed_body["exam_suggestion_dismissal_reason"] == "用户选择普通扫描"

        repeated = client.put(
            f"/v1/pages/{page_id}/exam-suggestion-dismissal",
            json={"result_version": 1, "reason": "用户选择普通扫描"},
            headers=owner_headers,
        )
        assert repeated.status_code == 200

        stale = client.put(
            f"/v1/pages/{page_id}/exam-suggestion-dismissal",
            json={"result_version": 2},
            headers=owner_headers,
        )
        assert stale.status_code == 409
        assert stale.json() == {"detail": "exam_suggestion_not_current"}


def test_exam_mode_is_user_selected_and_manual_edit_invalidates_classification() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "exam_explicit")
        page_id = create_and_process_page(client, headers, mode="exam")

        page = client.get(f"/v1/pages/{page_id}", headers=headers).json()
        assert page["exam_classifier_version"] == "user-selected-exam-v1"
        assert page["exam_probability"] == 1.0
        assert page["exam_details"]["source"] == "user_selected"

        rotated = client.post(
            f"/v1/pages/{page_id}/rotations",
            json={"degrees": 90},
            headers=headers,
        )
        assert rotated.status_code == 200
        assert rotated.json()["exam_classification_status"] == "stale"
        assert rotated.json()["exam_result_version"] is None
        assert rotated.json()["exam_prediction"] is None
        assert rotated.json()["exam_suggestion_visible"] is False


def test_exam_suggestion_dismissal_is_owner_only_and_denials_are_audited() -> None:
    with TestClient(main.app) as client:
        owner_headers, owner_name = register(client, "exam_matrix_owner")
        attacker_headers, _ = register(client, "exam_matrix_attacker")
        admin_headers, admin_name = register(client, "exam_matrix_admin")
        with SessionLocal() as db:
            admin = db.scalar(select(User).where(User.username == admin_name))
            owner = db.scalar(select(User).where(User.username == owner_name))
            assert admin is not None and owner is not None
            admin.role = Role.admin
            owner_id = owner.id
            db.commit()
        page_id = create_and_process_page(client, owner_headers)

        for headers in (attacker_headers, admin_headers):
            response = client.put(
                f"/v1/pages/{page_id}/exam-suggestion-dismissal",
                json={"result_version": 1},
                headers=headers,
            )
            assert response.status_code == 404

        with SessionLocal() as db:
            denials = db.scalars(
                select(AuditLog).where(
                    AuditLog.action == "dismiss_exam_suggestion",
                    AuditLog.object_id == page_id,
                    AuditLog.result == "denied",
                )
            ).all()
        assert len(denials) == 2
        assert {item.target_user_id for item in denials} == {owner_id}


def test_book_mode_disables_exam_classification() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "exam_book")
        page_id = create_and_process_page(client, headers, mode="book")

        page = client.get(f"/v1/pages/{page_id}", headers=headers).json()
        assert page["exam_classification_status"] == "disabled"
        assert page["exam_result_version"] is None
        assert page["exam_suggestion_visible"] is False
