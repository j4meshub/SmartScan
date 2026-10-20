from __future__ import annotations

import json
import signal
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from PIL import Image, ImageEnhance, ImageFilter, ImageOps, ImageStat
from sqlalchemy import or_, select

from services.api.app.account_deletion import process_next_due_account_deletion
from services.api.app.config import get_settings
from services.api.app.database import SessionLocal
from services.api.app.migrations import ensure_database_current
from services.api.app.models import JobStatus, PageReviewStatus, ProcessingJob, ScanPage
from services.api.app.page_service import save_page_result
from services.worker.app.vision import correct_document_perspective

settings = get_settings()
running = True


def stop(*_: object) -> None:
    global running
    running = False


def claim_job() -> str | None:
    now = datetime.now(UTC)
    with SessionLocal() as db:
        job = db.scalar(
            select(ProcessingJob)
            .where(
                ProcessingJob.status.in_([JobStatus.pending, JobStatus.running]),
                or_(ProcessingJob.lease_until.is_(None), ProcessingJob.lease_until < now),
            )
            .order_by(ProcessingJob.created_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not job:
            return None
        job.status = JobStatus.running
        job.attempts += 1
        job.lease_until = now + timedelta(minutes=5)
        db.commit()
        return job.id


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


def process(job_id: str) -> None:
    with SessionLocal() as db:
        job = db.get(ProcessingJob, job_id)
        page = db.get(ScanPage, job.page_id) if job and job.page_id else None
        if not job or not page:
            return
        source = settings.storage_root / page.original_path
        output: Path | None = None
        try:
            with Image.open(source) as raw:
                image = ImageOps.exif_transpose(raw).convert("RGB")
                correct_edges = job.kind in {"document", "exam"}
                edges_detected = True
                if correct_edges:
                    perspective = correct_document_perspective(
                        image,
                        min_area_ratio=settings.vision_document_min_area_ratio,
                        max_detection_dimension=settings.vision_max_detection_dimension,
                    )
                    image = perspective.image
                    edges_detected = perspective.detected
                page.quality_score, page.quality_warning, quality_details = quality_assessment(
                    image,
                    document_edges_required=correct_edges,
                    document_edges_detected=edges_detected,
                )
                page.quality_details = json.dumps(
                    quality_details, sort_keys=True, separators=(",", ":")
                )
                page.review_status = (
                    PageReviewStatus.pending
                    if page.quality_warning
                    else PageReviewStatus.not_required
                )
                page.review_reason = page.quality_warning
                page.reviewed_by_user_id = None
                page.reviewed_at = None
                image = ImageOps.autocontrast(image, cutoff=1)
                image = ImageEnhance.Sharpness(image).enhance(1.15)
                image = image.filter(ImageFilter.UnsharpMask(radius=1.2, percent=110, threshold=3))
                if page.rotation_degrees:
                    image = image.rotate(-page.rotation_degrees, expand=True)
                _, output = save_page_result(
                    db,
                    page=page,
                    image=image,
                    result_type="baseline",
                    processor_version="baseline-v1",
                    rotation_degrees=page.rotation_degrees,
                    settings=settings,
                )
            job.status = JobStatus.completed
            job.error = None
        except Exception as exc:  # keep originals and expose a recoverable failure
            job.status = JobStatus.failed if job.attempts >= 3 else JobStatus.pending
            job.error = str(exc)[:1000]
            if output is not None and output.exists():
                output.unlink()
        finally:
            job.lease_until = None
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
        job_id = claim_job()
        if job_id:
            process(job_id)
        else:
            time.sleep(1.0)


if __name__ == "__main__":
    main()
