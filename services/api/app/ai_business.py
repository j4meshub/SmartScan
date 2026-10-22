from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .config import get_settings
from .models import (
    AiEnhancementTask,
    AiMediaGrant,
    JobStatus,
    ProcessingJob,
    ScanPage,
    ScanProject,
    User,
)
from .schemas import AiEnhancementView

AI_CONSENT_VERSION = "2026-10-22.1"
AI_TRANSMISSION_NOTICE_CODE = "ai_data_transfer_v1"
AI_ENHANCEMENT_KINDS = ("recommended", "complex_ocr", "exam_review", "book_review")
AI_TASK_TYPES = (
    "classify_page",
    "detect_orientation",
    "extract_title",
    "extract_page_number",
    "ocr_formula",
    "review_cleanup_mask",
    "review_book_split",
)


class AiBusinessError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409, *, persist: bool = False):
        super().__init__(code)
        self.code = code
        self.status_code = status_code
        self.persist = persist


@dataclass(frozen=True)
class EnhancementCreation:
    task: AiEnhancementTask
    replayed: bool


def requested_tasks_for(project: ScanProject, enhancement_kind: str) -> tuple[str, ...]:
    if enhancement_kind == "recommended":
        tasks = ["classify_page", "detect_orientation", "extract_title"]
        if project.mode == "book":
            tasks.append("extract_page_number")
        return tuple(tasks)
    if enhancement_kind == "complex_ocr":
        return ("ocr_formula",)
    if enhancement_kind == "exam_review":
        if project.mode != "exam":
            raise AiBusinessError("ai_enhancement_kind_not_supported_for_project", 422)
        return ("review_cleanup_mask",)
    if enhancement_kind == "book_review":
        if project.mode != "book":
            raise AiBusinessError("ai_enhancement_kind_not_supported_for_project", 422)
        return ("review_book_split",)
    raise AiBusinessError("ai_enhancement_kind_invalid", 422)


def configure_project_ai(
    db: Session,
    *,
    project: ScanProject,
    actor: User,
    enabled: bool,
    consent_version: str | None,
) -> ScanProject:
    locked = db.scalar(select(ScanProject).where(ScanProject.id == project.id).with_for_update())
    if locked is None:
        raise AiBusinessError("project_not_found", 404)
    project = locked
    if project.owner_user_id != actor.id:
        raise AiBusinessError("project_not_found", 404)
    if enabled and consent_version != AI_CONSENT_VERSION:
        raise AiBusinessError("ai_consent_version_required", 422)
    project.ai_enabled = enabled
    if enabled:
        project.ai_consent_version = AI_CONSENT_VERSION
        project.ai_enabled_by_user_id = actor.id
        project.ai_enabled_at = datetime.now(UTC)
    else:
        db.execute(
            update(AiMediaGrant)
            .where(
                AiMediaGrant.project_id == project.id,
                AiMediaGrant.revoked_at.is_(None),
            )
            .values(revoked_at=datetime.now(UTC))
        )
    project.updated_at = datetime.now(UTC)
    return project


def create_enhancement(
    db: Session,
    *,
    page: ScanPage,
    actor: User,
    enhancement_kind: str,
    source_result_version: int,
    idempotency_key: str,
) -> EnhancementCreation:
    locked_page = db.scalar(
        select(ScanPage)
        .where(ScanPage.id == page.id, ScanPage.owner_user_id == actor.id)
        .with_for_update()
    )
    if locked_page is None:
        raise AiBusinessError("page_not_found", 404)
    page = locked_page
    if page.owner_user_id != actor.id:
        raise AiBusinessError("page_not_found", 404)
    project = db.scalar(
        select(ScanProject).where(ScanProject.id == page.project_id).with_for_update()
    )
    if project is None or project.owner_user_id != actor.id:
        raise AiBusinessError("page_not_found", 404)
    if not project.ai_enabled or project.ai_consent_version != AI_CONSENT_VERSION:
        raise AiBusinessError("project_ai_not_enabled")
    if page.active_result_version <= 0:
        raise AiBusinessError("page_result_not_ready")
    if source_result_version != page.active_result_version:
        raise AiBusinessError("ai_source_version_conflict")
    tasks = requested_tasks_for(project, enhancement_kind)
    existing = db.scalar(
        select(AiEnhancementTask).where(
            AiEnhancementTask.page_id == page.id,
            AiEnhancementTask.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        if (
            existing.enhancement_kind != enhancement_kind
            or existing.source_result_version != source_result_version
        ):
            raise AiBusinessError("ai_idempotency_conflict")
        return EnhancementCreation(existing, replayed=True)

    task = AiEnhancementTask(
        owner_user_id=actor.id,
        project_id=project.id,
        page_id=page.id,
        idempotency_key=idempotency_key,
        enhancement_kind=enhancement_kind,
        requested_tasks=json.dumps(tasks, ensure_ascii=False, separators=(",", ":")),
        source_result_version=source_result_version,
        status="queued",
    )
    db.add(task)
    db.flush()
    settings = get_settings()
    job = ProcessingJob(
        owner_user_id=actor.id,
        project_id=project.id,
        page_id=page.id,
        kind="ai_enhancement",
        max_attempts=settings.job_max_attempts,
    )
    db.add(job)
    db.flush()
    task.processing_job_id = job.id
    return EnhancementCreation(task, replayed=False)


def mark_page_enhancements_stale(
    db: Session,
    *,
    page_id: str,
    active_result_version: int,
) -> None:
    now = datetime.now(UTC)
    db.execute(
        update(AiMediaGrant)
        .where(
            AiMediaGrant.page_id == page_id,
            AiMediaGrant.source_result_version != active_result_version,
            AiMediaGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    processing_job_ids = list(
        db.scalars(
            select(AiEnhancementTask.processing_job_id).where(
                AiEnhancementTask.page_id == page_id,
                AiEnhancementTask.source_result_version != active_result_version,
                AiEnhancementTask.status.in_(("queued", "processing", "candidate_ready")),
                AiEnhancementTask.processing_job_id.is_not(None),
            )
        )
    )
    db.execute(
        update(AiEnhancementTask)
        .where(
            AiEnhancementTask.page_id == page_id,
            AiEnhancementTask.source_result_version != active_result_version,
            AiEnhancementTask.status.in_(("queued", "processing", "candidate_ready")),
        )
        .values(status="stale", updated_at=now)
    )
    if processing_job_ids:
        db.execute(
            update(ProcessingJob)
            .where(
                ProcessingJob.id.in_(processing_job_ids),
                ProcessingJob.status.not_in(
                    (JobStatus.ready, JobStatus.failed_final, JobStatus.canceled)
                ),
            )
            .values(
                status=JobStatus.canceled,
                progress=0,
                cancel_requested_at=now,
                canceled_at=now,
                lease_owner=None,
                lease_token=None,
                lease_until=None,
                heartbeat_at=None,
                updated_at=now,
            )
        )


def accept_enhancement(
    db: Session,
    *,
    task: AiEnhancementTask,
    page: ScanPage,
    actor: User,
) -> tuple[AiEnhancementTask, Path | None]:
    if task.owner_user_id != actor.id or page.owner_user_id != actor.id:
        raise AiBusinessError("ai_enhancement_not_found", 404)
    if page.active_result_version != task.source_result_version:
        task.status = "stale"
        task.updated_at = datetime.now(UTC)
        raise AiBusinessError("ai_source_version_conflict", persist=True)
    if task.status != "candidate_ready" or task.candidate_result is None:
        raise AiBusinessError("ai_candidate_not_ready")
    try:
        candidate = json.loads(task.candidate_result)
    except json.JSONDecodeError as exc:
        raise AiBusinessError("ai_candidate_invalid", 422) from exc
    candidate_tasks = candidate.get("tasks", {}) if isinstance(candidate, dict) else {}
    if not isinstance(candidate_tasks, dict):
        raise AiBusinessError("ai_candidate_invalid", 422)

    destination: Path | None = None
    applied: dict[str, object] = {}
    orientation = candidate_tasks.get("detect_orientation")
    if isinstance(orientation, dict):
        degrees = orientation.get("rotation_degrees")
        if degrees not in {0, 90, 180, 270}:
            raise AiBusinessError("ai_orientation_candidate_invalid", 422)
        if degrees:
            from .page_service import PageMutationError, rotate_page

            try:
                page, destination = rotate_page(
                    db,
                    actor=actor,
                    page_id=page.id,
                    degrees=int(degrees),
                )
            except PageMutationError as exc:
                raise AiBusinessError(exc.code, exc.status_code) from exc
            applied["rotation_degrees"] = int(degrees)

    project = db.scalar(
        select(ScanProject).where(ScanProject.id == task.project_id).with_for_update()
    )
    if project is None or project.owner_user_id != actor.id:
        raise AiBusinessError("ai_enhancement_not_found", 404)
    title_result = candidate_tasks.get("extract_title")
    if isinstance(title_result, dict) and isinstance(title_result.get("candidates"), list):
        from services.worker.app.ocr import sanitize_title_candidate

        titles = [item for item in title_result["candidates"] if isinstance(item, dict)]
        titles.sort(key=lambda item: float(item.get("confidence", 0.0)), reverse=True)
        title = sanitize_title_candidate(str(titles[0].get("text", ""))) if titles else None
        if title:
            project.suggested_name = title
            project.suggested_name_source = "ai"
            project.suggested_name_updated_at = datetime.now(UTC)
            applied["suggested_name"] = title

    page_number = candidate_tasks.get("extract_page_number")
    if (
        project.mode == "book"
        and isinstance(page_number, dict)
        and page_number.get("status") == "detected"
    ):
        value = page_number.get("normalized_number")
        label = page_number.get("raw_label")
        style = page_number.get("style")
        confidence = page_number.get("confidence")
        if (
            not isinstance(value, int)
            or not isinstance(label, str)
            or style not in {"arabic", "roman"}
            or not isinstance(confidence, (int, float))
        ):
            raise AiBusinessError("ai_page_number_candidate_invalid", 422)
        page.book_page_number_status = "ready"
        page.book_page_number_value = value
        page.book_page_number_label = label
        page.book_page_number_kind = str(style)
        page.book_page_number_confidence = float(confidence)
        page.book_page_number_reason = "ai_user_accepted"
        page.book_page_number_result_version = page.active_result_version
        applied["book_page_number"] = label

    evidence = _json_object(task.evidence) or {}
    evidence["accepted_application"] = {
        "applied": applied,
        "source_result_version": task.source_result_version,
        "active_result_version": page.active_result_version,
    }
    task.evidence = json.dumps(evidence, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    task.status = "accepted"
    task.accepted_by_user_id = actor.id
    task.accepted_at = datetime.now(UTC)
    task.updated_at = task.accepted_at
    return task, destination


def reject_enhancement(
    *, task: AiEnhancementTask, page: ScanPage, actor: User
) -> AiEnhancementTask:
    if task.owner_user_id != actor.id or page.owner_user_id != actor.id:
        raise AiBusinessError("ai_enhancement_not_found", 404)
    if page.active_result_version != task.source_result_version:
        task.status = "stale"
        task.updated_at = datetime.now(UTC)
        raise AiBusinessError("ai_source_version_conflict", persist=True)
    if task.status != "candidate_ready":
        raise AiBusinessError("ai_candidate_not_ready")
    task.status = "rejected"
    task.rejected_at = datetime.now(UTC)
    return task


def _json_object(raw: str | None) -> dict[str, object] | None:
    if raw is None:
        return None
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return None
    return value if isinstance(value, dict) else None


def enhancement_view(task: AiEnhancementTask) -> AiEnhancementView:
    try:
        requested = json.loads(task.requested_tasks)
    except json.JSONDecodeError:
        requested = []
    if not isinstance(requested, list) or not all(isinstance(item, str) for item in requested):
        requested = []
    public_results = task.status in {"candidate_ready", "accepted", "rejected", "stale"}
    return AiEnhancementView(
        id=task.id,
        project_id=task.project_id,
        page_id=task.page_id,
        processing_job_id=task.processing_job_id,
        enhancement_kind=task.enhancement_kind,
        requested_tasks=requested,
        source_result_version=task.source_result_version,
        status=task.status,
        candidate_result=_json_object(task.candidate_result) if public_results else None,
        evidence=_json_object(task.evidence) if public_results else None,
        provider_id=task.provider_id,
        model=task.model,
        confidence=task.confidence,
        error_code=task.error_code,
        accepted_by_user_id=task.accepted_by_user_id,
        accepted_at=task.accepted_at,
        rejected_at=task.rejected_at,
        created_at=task.created_at,
        updated_at=task.updated_at,
    )
