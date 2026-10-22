from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi.testclient import TestClient
from test_ai_business import create_enhancement, create_processed_page, enable_ai, register

from services.api.app import main
from services.api.app.config import Settings
from services.api.app.database import SessionLocal
from services.api.app.job_service import JobClaim, claim_ai_job_by_id
from services.api.app.models import (
    AiEnhancementTask,
    JobStatus,
    ProcessingJob,
    ScanPage,
    ScanProject,
)
from services.worker.app.ai_gateway import AiGatewayError, AiGatewayResult
from services.worker.app.ai_main import process_ai_claim


class FakeCommonGateway:
    def __init__(
        self,
        *,
        fail_once_on: str | None = None,
        retryable: bool = True,
        mismatch_evidence: bool = False,
    ) -> None:
        self.calls: list[str] = []
        self.fail_once_on = fail_once_on
        self.retryable = retryable
        self.mismatch_evidence = mismatch_evidence
        self.failed = False

    def execute(
        self,
        *,
        enhancement_task_id: str,
        task: dict[str, Any],
        media: object,
    ) -> AiGatewayResult:
        del enhancement_task_id, media
        task_type = str(task["task_type"])
        self.calls.append(task_type)
        if task_type == self.fail_once_on and not self.failed:
            self.failed = True
            raise AiGatewayError("ai_gateway_timeout", retryable=self.retryable)
        task_id = str(task["task_id"])
        common = {
            "schema_version": "1.0",
            "task_id": task_id,
            "task_type": task_type,
            "confidence": 0.94,
        }
        if task_type == "classify_page":
            result = {**common, "label": "ordinary_document", "evidence_codes": ["ordinary_layout"]}
        elif task_type == "detect_orientation":
            result = {**common, "rotation_degrees": 90, "evidence_codes": ["text_direction"]}
        elif task_type == "extract_title":
            result = {
                **common,
                "candidates": [{"text": "AI 建议标题", "confidence": 0.93, "source": "header"}],
            }
        elif task_type == "extract_page_number":
            result = {
                **common,
                "status": "detected",
                "normalized_number": 12,
                "raw_label": "12",
                "style": "arabic",
            }
        else:
            raise AssertionError(f"测试网关不支持 {task_type}")
        evidence = {
            "provider_id": "mock-common",
            "provider_kind": "custom_vlm",
            "api_style": "openai_responses",
            "model_version": "mock-v1",
            "schema_version": "1.0",
            "result_schema_sha256": "a" * 64,
            "task_id": task_id,
            "task_type": task_type,
            "page_id": task["context"]["page_id"],
            "source_result_version": task["context"]["source_result_version"],
            "media_sha256": task["context"]["media"]["sha256"],
            "disposition": "candidate",
            "business_mutation_allowed": False,
            "result": result,
            "unexpected_secret": "must-not-be-persisted",
        }
        if self.mismatch_evidence:
            evidence["page_id"] = "00000000-0000-4000-8000-000000000000"
        return AiGatewayResult(evidence=evidence, network={"network_ready": True})


def test_ai_runtime_capability_requires_complete_safe_server_configuration() -> None:
    configured = Settings(
        _env_file=None,
        ai_gateway_url="http://ai-gateway:8010",
        ai_internal_token="i" * 32,
        ai_provider_id="vision-main",
        ai_media_base_url="https://scan.example/api/v1/ai-media/",
    )
    assert configured.ai_runtime_configured() is True
    short_token = Settings(
        _env_file=None,
        ai_gateway_url="http://ai-gateway:8010",
        ai_internal_token="short",
        ai_provider_id="vision-main",
        ai_media_base_url="https://scan.example/api/v1/ai-media/",
    )
    assert short_token.ai_runtime_configured() is False
    unsafe_media = Settings(
        _env_file=None,
        ai_gateway_url="http://ai-gateway:8010",
        ai_internal_token="i" * 32,
        ai_provider_id="vision-main",
        ai_media_base_url="http://scan.example/media/",
    )
    assert unsafe_media.ai_runtime_configured() is False


def _claim(
    task_view: dict[str, object], *, worker_id: str, now: datetime | None = None
) -> JobClaim:
    with SessionLocal() as db:
        claim = claim_ai_job_by_id(
            db,
            str(task_view["processing_job_id"]),
            worker_id=worker_id,
            now=now,
        )
        assert claim is not None
        db.commit()
        return claim


def test_common_ai_worker_only_creates_candidates_until_user_accepts() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_common")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-common-flow-0001")
        gateway = FakeCommonGateway()

        process_ai_claim(_claim(task_view, worker_id="ai-common-worker"), gateway=gateway)

        with SessionLocal() as db:
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            page = db.get(ScanPage, page_id)
            project = db.get(ScanProject, project_id)
            job = db.get(ProcessingJob, str(task_view["processing_job_id"]))
            assert task is not None and task.status == "candidate_ready"
            assert task.confidence == 0.94
            assert page is not None and page.active_result_version == 1
            assert page.rotation_degrees == 0
            assert project is not None and project.suggested_name_source != "ai"
            assert job is not None and job.status == JobStatus.ready
            assert "must-not-be-persisted" not in str(task.evidence)

        listed = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=headers)
        assert listed.status_code == 200
        candidate = listed.json()[0]
        assert candidate["status"] == "candidate_ready"
        assert set(candidate["candidate_result"]["tasks"]) == {
            "classify_page",
            "detect_orientation",
            "extract_title",
        }

        accepted = client.post(f"/v1/ai-enhancements/{task_view['id']}/accept", headers=headers)
        assert accepted.status_code == 200, accepted.text
        assert accepted.json()["status"] == "accepted"
        assert accepted.json()["evidence"]["accepted_application"]["applied"] == {
            "rotation_degrees": 90,
            "suggested_name": "AI 建议标题",
        }
        with SessionLocal() as db:
            page = db.get(ScanPage, page_id)
            project = db.get(ScanProject, project_id)
            assert page is not None and page.active_result_version == 2
            assert page.rotation_degrees == 90
            assert project is not None and project.title == "AI 业务编排"
            assert project.suggested_name == "AI 建议标题"
            assert project.suggested_name_source == "ai"


def test_common_ai_worker_resumes_completed_steps_without_duplicate_results() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_resume")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-common-resume-0001")
        gateway = FakeCommonGateway(fail_once_on="detect_orientation", retryable=True)

        process_ai_claim(_claim(task_view, worker_id="ai-resume-1"), gateway=gateway)
        with SessionLocal() as db:
            job = db.get(ProcessingJob, str(task_view["processing_job_id"]))
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            assert job is not None and job.status == JobStatus.failed_retryable
            assert task is not None and task.status == "queued"
            job.available_at = datetime.now(UTC)
            db.commit()
        hidden = client.get(f"/v1/pages/{page_id}/ai-enhancements", headers=headers).json()[0]
        assert hidden["candidate_result"] is None
        assert hidden["evidence"] is None

        retry_at = datetime.now(UTC) + timedelta(seconds=1)
        process_ai_claim(
            _claim(task_view, worker_id="ai-resume-2", now=retry_at),
            gateway=gateway,
        )
        assert gateway.calls.count("classify_page") == 1
        assert gateway.calls.count("detect_orientation") == 2
        with SessionLocal() as db:
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            assert task is not None and task.status == "candidate_ready"


def test_book_page_number_is_only_applied_after_acceptance() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_book_number")
        project_id, page_id = create_processed_page(client, headers, mode="book")
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-book-number-0001")

        process_ai_claim(
            _claim(task_view, worker_id="ai-book-number"),
            gateway=FakeCommonGateway(),
        )
        with SessionLocal() as db:
            page = db.get(ScanPage, page_id)
            assert page is not None and page.book_page_number_value is None

        accepted = client.post(f"/v1/ai-enhancements/{task_view['id']}/accept", headers=headers)
        assert accepted.status_code == 200, accepted.text
        with SessionLocal() as db:
            page = db.get(ScanPage, page_id)
            assert page is not None
            assert page.book_page_number_status == "ready"
            assert page.book_page_number_value == 12
            assert page.book_page_number_label == "12"
            assert page.book_page_number_kind == "arabic"
            assert page.book_page_number_reason == "ai_user_accepted"
            assert page.book_page_number_result_version == page.active_result_version == 2


def test_non_retryable_ai_failure_preserves_base_page() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_degrade")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-common-degrade-0001")
        gateway = FakeCommonGateway(fail_once_on="classify_page", retryable=False)

        process_ai_claim(_claim(task_view, worker_id="ai-degrade"), gateway=gateway)

        with SessionLocal() as db:
            job = db.get(ProcessingJob, str(task_view["processing_job_id"]))
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            page = db.get(ScanPage, page_id)
            assert job is not None and job.status == JobStatus.failed_final
            assert task is not None and task.status == "failed"
            assert task.error_code == "ai_gateway_timeout"
            assert page is not None and page.active_result_version == 1
        preview = client.get(f"/v1/pages/{page_id}/content", headers=headers)
        assert preview.status_code == 200


def test_mismatched_gateway_evidence_is_rejected_without_mutating_page() -> None:
    with TestClient(main.app) as client:
        headers, _ = register(client, "ai_mismatch")
        project_id, page_id = create_processed_page(client, headers)
        enable_ai(client, headers, project_id)
        task_view = create_enhancement(client, headers, page_id, "ai-common-mismatch-0001")

        process_ai_claim(
            _claim(task_view, worker_id="ai-mismatch"),
            gateway=FakeCommonGateway(mismatch_evidence=True),
        )
        with SessionLocal() as db:
            task = db.get(AiEnhancementTask, str(task_view["id"]))
            page = db.get(ScanPage, page_id)
            assert task is not None and task.status == "failed"
            assert task.error_code == "ai_gateway_evidence_mismatch"
            assert page is not None and page.active_result_version == 1
