from __future__ import annotations

import json
import os
import signal
import socket
import time
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
from sqlalchemy import select

from services.api.app.account_deletion import process_next_due_account_deletion
from services.api.app.config import get_settings
from services.api.app.database import SessionLocal
from services.api.app.job_service import (
    JobClaim,
    claim_next_job,
    heartbeat_job,
    mark_job_failure,
)
from services.api.app.migrations import ensure_database_current
from services.api.app.models import JobStatus, PageReviewStatus, ProcessingJob, ScanPage
from services.api.app.page_service import save_page_result
from services.worker.app.vision import correct_document_perspective

settings = get_settings()
running = True
worker_id = f"{socket.gethostname()}:{os.getpid()}"


def stop(*_: object) -> None:
    global running
    running = False


def claim_job() -> JobClaim | None:
    with SessionLocal() as db:
        claim = claim_next_job(db, worker_id=worker_id, settings=settings)
        db.commit()
        return claim


def heartbeat(claim: JobClaim, progress: int) -> bool:
    with SessionLocal() as db:
        accepted = heartbeat_job(db, claim, progress=progress, settings=settings)
        db.commit()
        return accepted


def quality_warning(
    image: Image.Image,
    *,
    document_edges_required: bool = False,
    document_edges_detected: bool = True,
) -> str | None:
    return quality_assessment(
        image,
        document_edges_required=document_edges_required,
        document_edges_detected=document_edges_detected,
    )[1]


def quality_assessment(
    image: Image.Image,
    *,
    document_edges_required: bool = False,
    document_edges_detected: bool = True,
) -> tuple[float, str | None, dict[str, object]]:
    gray = ImageOps.grayscale(image).resize((256, 256))
    extrema = gray.getextrema()
    brightness = float(ImageStat.Stat(gray).mean[0])
    contrast_range = int(extrema[1] - extrema[0])
    warnings: list[str] = []
    if image.width * image.height < 1_000_000:
        warnings.append("low_resolution")
    if contrast_range < 45:
        warnings.append("low_contrast")
    if document_edges_required and not document_edges_detected:
        warnings.append("document_edges_not_found")
    score = max(0.0, 100.0 - len(warnings) * 30.0)
    details: dict[str, object] = {
        "width": image.width,
        "height": image.height,
        "pixel_count": image.width * image.height,
        "brightness": round(brightness, 2),
        "contrast_range": contrast_range,
        "document_edges_detected": document_edges_detected,
        "warnings": warnings,
    }
    return score, warnings[0] if warnings else None, details


def process(claim: JobClaim) -> None:
    page_id: str | None = None
    source: Path | None = None
    job_kind = "document"
    rotation_degrees = 0
    page_missing = False
    with SessionLocal() as db:
        job = db.get(ProcessingJob, claim.job_id)
        if (
            not job
            or job.status != JobStatus.baseline_processing
            or job.lease_token != claim.lease_token
        ):
            return
        page = db.get(ScanPage, job.page_id) if job.page_id else None
        if page is None:
            page_missing = True
        else:
            source = settings.storage_root / page.original_path
            page_id = page.id
            job_kind = job.kind
            rotation_degrees = page.rotation_degrees
    if page_missing:
        with SessionLocal() as db:
            mark_job_failure(
                db,
                claim,
                error_code="page_missing",
                error="page_missing",
                settings=settings,
            )
            db.commit()
        return
    output: Path | None = None
    try:
        if not heartbeat(claim, 15):
            return
        assert source is not None and page_id is not None
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            correct_edges = job_kind in {"document", "exam"}
            edges_detected = True
            if correct_edges:
                perspective = correct_document_perspective(
                    image,
                    min_area_ratio=settings.vision_document_min_area_ratio,
                    max_detection_dimension=settings.vision_max_detection_dimension,
                )
                image = perspective.image
                edges_detected = perspective.detected
            quality_score, quality_warning_value, quality_details = quality_assessment(
                image,
                document_edges_required=correct_edges,
                document_edges_detected=edges_detected,
            )
            image = ImageOps.autocontrast(image, cutoff=1)
            image = ImageEnhance.Sharpness(image).enhance(1.15)
            image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
            if rotation_degrees:
                image = image.rotate(-rotation_degrees, expand=True)
            rendered = image.copy()
        if not heartbeat(claim, 70):
            return
        with SessionLocal() as db:
            job = db.scalar(
                select(ProcessingJob).where(ProcessingJob.id == claim.job_id).with_for_update()
            )
            page = db.scalar(select(ScanPage).where(ScanPage.id == page_id).with_for_update())
            if (
                job is None
                or page is None
                or job.status != JobStatus.baseline_processing
                or job.lease_token != claim.lease_token
                or job.cancel_requested_at is not None
            ):
                return
            page.quality_score = quality_score
            page.quality_warning = quality_warning_value
            page.quality_details = json.dumps(
                quality_details, sort_keys=True, separators=(",", ":")
            )
            page.review_status = (
                PageReviewStatus.pending if page.quality_warning else PageReviewStatus.not_required
            )
            page.review_reason = page.quality_warning
            page.reviewed_by_user_id = None
            page.reviewed_at = None
            result, output = save_page_result(
                db,
                page=page,
                image=rendered,
                result_type="baseline",
                processor_version="baseline-v1",
                rotation_degrees=page.rotation_degrees,
                settings=settings,
            )
            now = datetime.now(UTC)
            job.status = JobStatus.baseline_ready
            job.baseline_ready_at = now
            job.progress = 90
            job.result_version = result.version
            # 可选增强默认关闭；基础结果就绪后直接进入最终可用状态。
            job.status = JobStatus.ready
            job.progress = 100
            job.completed_at = now
            job.error_code = None
            job.error = None
            job.lease_owner = None
            job.lease_token = None
            job.lease_until = None
            job.heartbeat_at = None
            db.commit()
    except Exception as exc:  # keep originals and expose a recoverable failure
        if output is not None and output.exists():
            output.unlink()
        with SessionLocal() as db:
            mark_job_failure(
                db,
                claim,
                error_code="baseline_processing_failed",
                error=type(exc).__name__,
                settings=settings,
            )
            db.commit()


def process_account_deletion_queue() -> bool:
    with SessionLocal() as db:
        result = process_next_due_account_deletion(db, settings=settings)
        return result is not None


def main() -> None:
    ensure_database_current()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    next_deletion_sweep = 0.0
    while running:
        now_monotonic = time.monotonic()
        if now_monotonic >= next_deletion_sweep:
            try:
                process_account_deletion_queue()
            except Exception as exc:
                print(f"账号删除任务失败：{type(exc).__name__}", flush=True)
            next_deletion_sweep = now_monotonic + 30.0
        claim = claim_job()
        if claim:
            process(claim)
        else:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
