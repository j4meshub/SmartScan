from __future__ import annotations

import json
import os
import signal
import socket
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from PIL import Image, ImageOps
from sqlalchemy import select

from services.api.app.ai_media import issue_media_grant, revoke_task_media_grants
from services.api.app.config import get_settings
from services.api.app.database import SessionLocal
from services.api.app.job_service import (
    JobClaim,
    claim_next_ai_job,
    heartbeat_job,
    mark_job_failure,
)
from services.api.app.migrations import ensure_database_current
from services.api.app.models import AiEnhancementTask, JobStatus, PageResult, ProcessingJob
from services.api.app.worker_status import record_worker_heartbeat
from services.worker.app.ai_gateway import AiGatewayClient, AiGatewayError
from services.worker.app.ai_tasks import (
    AiTaskBuildError,
    build_task_payload,
    load_checkpoint,
    load_task_context,
    requested_common_tasks,
    sanitized_evidence,
    validate_gateway_evidence,
)

settings = get_settings()
running = True
worker_id = f"ai:{socket.gethostname()}:{os.getpid()}"


def stop(*_: object) -> None:
    global running
    running = False


def _heartbeat(claim: JobClaim, progress: int) -> bool:
    with SessionLocal() as db:
        accepted = heartbeat_job(db, claim, progress=progress, settings=settings)
        record_worker_heartbeat(db, worker_id=worker_id, busy_job_id=claim.job_id)
        db.commit()
        return accepted


def _claim() -> JobClaim | None:
    with SessionLocal() as db:
        claim = claim_next_ai_job(db, worker_id=worker_id, settings=settings)
        record_worker_heartbeat(
            db,
            worker_id=worker_id,
            busy_job_id=claim.job_id if claim is not None else None,
        )
        db.commit()
        return claim


def _source_path(claim: JobClaim) -> tuple[str, Path]:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, claim.job_id)
        enhancement = db.scalar(
            select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == claim.job_id)
        )
        if (
            job is None
            or enhancement is None
            or job.status != JobStatus.optional_enhancing
            or job.lease_token != claim.lease_token
        ):
            raise AiTaskBuildError("ai_job_lease_lost")
        result = db.scalar(
            select(PageResult).where(
                PageResult.page_id == enhancement.page_id,
                PageResult.version == enhancement.source_result_version,
            )
        )
        if result is None:
            raise AiTaskBuildError("ai_source_missing")
        source = (settings.storage_root.resolve() / result.file_path).resolve()
        if settings.storage_root.resolve() not in source.parents or not source.is_file():
            raise AiTaskBuildError("ai_source_missing")
        enhancement_id = enhancement.id
        return enhancement_id, source


def _save_step(
    claim: JobClaim,
    *,
    task_type: str,
    payload: dict[str, Any],
    evidence: dict[str, Any],
) -> bool:
    result = validate_gateway_evidence(payload, evidence)
    with SessionLocal() as db:
        job = db.scalar(
            select(ProcessingJob).where(ProcessingJob.id == claim.job_id).with_for_update()
        )
        enhancement = db.scalar(
            select(AiEnhancementTask)
            .where(AiEnhancementTask.processing_job_id == claim.job_id)
            .with_for_update()
        )
        if (
            job is None
            or enhancement is None
            or job.status != JobStatus.optional_enhancing
            or job.lease_token != claim.lease_token
            or enhancement.status != "processing"
        ):
            return False
        candidates = load_checkpoint(enhancement.candidate_result)
        proofs = load_checkpoint(enhancement.evidence)
        candidates["tasks"][task_type] = result
        proofs["tasks"][task_type] = sanitized_evidence(evidence)
        enhancement.candidate_result = json.dumps(
            candidates, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        enhancement.evidence = json.dumps(
            proofs, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        )
        db.commit()
        return True


def _finish_success(claim: JobClaim) -> None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        job = db.scalar(
            select(ProcessingJob).where(ProcessingJob.id == claim.job_id).with_for_update()
        )
        enhancement = db.scalar(
            select(AiEnhancementTask)
            .where(AiEnhancementTask.processing_job_id == claim.job_id)
            .with_for_update()
        )
        if (
            job is None
            or enhancement is None
            or job.status != JobStatus.optional_enhancing
            or job.lease_token != claim.lease_token
        ):
            return
        candidates = load_checkpoint(enhancement.candidate_result)
        proofs = load_checkpoint(enhancement.evidence)
        requested = requested_common_tasks(enhancement)
        if any(
            task_type not in candidates["tasks"] or task_type not in proofs["tasks"]
            for task_type in requested
        ):
            raise AiTaskBuildError("ai_candidate_incomplete")
        confidences = [
            float(candidates["tasks"][task_type]["confidence"]) for task_type in requested
        ]
        first_proof = proofs["tasks"][requested[0]] if requested else {}
        enhancement.status = "candidate_ready"
        enhancement.provider_id = str(first_proof.get("provider_id") or "") or None
        enhancement.model = str(first_proof.get("model_version") or "") or None
        enhancement.confidence = min(confidences) if confidences else None
        enhancement.error_code = None
        enhancement.updated_at = now
        job.status = JobStatus.ready
        job.progress = 100
        job.result_version = enhancement.source_result_version
        job.completed_at = now
        job.error_code = None
        job.error = None
        job.lease_owner = None
        job.lease_token = None
        job.lease_until = None
        job.heartbeat_at = None
        revoke_task_media_grants(db, enhancement.id, now=now)
        db.commit()


def process_ai_claim(
    claim: JobClaim,
    *,
    gateway: AiGatewayClient | None = None,
) -> None:
    gateway = gateway or AiGatewayClient(settings)
    try:
        enhancement_id, source = _source_path(claim)
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw)
            with SessionLocal() as db:
                context = load_task_context(db, enhancement_id, image=image)
                requested = requested_common_tasks(context.enhancement)
                candidate_tasks = load_checkpoint(context.enhancement.candidate_result)["tasks"]
                evidence_tasks = load_checkpoint(context.enhancement.evidence)["tasks"]
                completed = set(candidate_tasks) & set(evidence_tasks)
        with SessionLocal() as db:
            issued = issue_media_grant(db, enhancement_task_id=enhancement_id, settings=settings)
            db.commit()
        pending = [task_type for task_type in requested if task_type not in completed]
        for index, task_type in enumerate(pending):
            if not _heartbeat(claim, 10 + int(index * 75 / max(len(pending), 1))):
                return
            with Image.open(source) as raw, SessionLocal() as db:
                context = load_task_context(db, enhancement_id, image=ImageOps.exif_transpose(raw))
                payload = build_task_payload(context, task_type)
            response = gateway.execute(
                enhancement_task_id=enhancement_id,
                task=payload,
                media=issued,
            )
            if not _save_step(
                claim,
                task_type=task_type,
                payload=payload,
                evidence=response.evidence,
            ):
                return
        _finish_success(claim)
    except AiGatewayError as exc:
        with SessionLocal() as db:
            mark_job_failure(
                db,
                claim,
                error_code=exc.code,
                error=exc.code,
                retryable=exc.retryable,
                settings=settings,
            )
            db.commit()
    except Exception as exc:
        code = str(exc) if isinstance(exc, AiTaskBuildError) else "ai_enhancement_failed"
        with SessionLocal() as db:
            mark_job_failure(
                db,
                claim,
                error_code=code,
                error=type(exc).__name__,
                retryable=False,
                settings=settings,
            )
            db.commit()


def main() -> None:
    ensure_database_current()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    while running:
        claim = _claim()
        if claim is None:
            time.sleep(1.0)
            continue
        process_ai_claim(claim)


if __name__ == "__main__":
    main()
