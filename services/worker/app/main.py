from __future__ import annotations

import json
import os
import signal
import socket
import time
from datetime import UTC, datetime
from functools import lru_cache
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
from services.api.app.models import (
    JobStatus,
    PageReviewStatus,
    ProcessingJob,
    ScanPage,
    ScanProject,
    User,
)
from services.api.app.page_service import save_page_result
from services.api.app.project_cleanup import process_next_project_cleanup
from services.api.app.upload_cleanup import process_next_upload_cleanup
from services.worker.app.exam import (
    ExamClassificationResult,
    LightweightExamClassifier,
    classify_exam_page,
)
from services.worker.app.ocr import (
    OcrAnalysis,
    OcrEngine,
    PaddleOcrEngine,
    analyze_four_orientations,
    default_document_name,
    rotate_clockwise,
)
from services.worker.app.vision import correct_document_perspective

settings = get_settings()
running = True
worker_id = f"{socket.gethostname()}:{os.getpid()}"


@lru_cache(maxsize=1)
def get_ocr_engine() -> OcrEngine:
    return PaddleOcrEngine(settings)


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


def process(
    claim: JobClaim,
    *,
    ocr_engine: OcrEngine | None = None,
    exam_model: LightweightExamClassifier | None = None,
) -> None:
    page_id: str | None = None
    source: Path | None = None
    job_kind = "document"
    rotation_degrees = 0
    locale = "zh-CN"
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
            owner = db.get(User, job.owner_user_id)
            locale = owner.locale if owner is not None else "zh-CN"
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
        analysis: OcrAnalysis | None = None
        if settings.ocr_enabled or ocr_engine is not None:
            if not heartbeat(claim, 20):
                return
            engine = ocr_engine or get_ocr_engine()
            analysis = analyze_four_orientations(
                rendered,
                engine,
                min_confidence=settings.ocr_min_confidence,
                title_min_confidence=settings.ocr_title_min_confidence,
                orientation_margin=settings.ocr_orientation_margin,
                on_pass=lambda index: heartbeat(claim, 20 + index * 15),
            )
            if analysis.rotation_degrees:
                rendered = rotate_clockwise(rendered, analysis.rotation_degrees)
        elif not heartbeat(claim, 80):
            return
        exam_classification: ExamClassificationResult | None = None
        if job_kind in {"document", "exam"}:
            if not heartbeat(claim, 85):
                return
            exam_classification = classify_exam_page(
                rendered,
                ocr_text=analysis.text if analysis is not None else None,
                explicit_exam_mode=job_kind == "exam",
                model=exam_model,
            )
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
            final_rotation = (
                page.rotation_degrees + (analysis.rotation_degrees if analysis else 0)
            ) % 360
            result, output = save_page_result(
                db,
                page=page,
                image=rendered,
                result_type="baseline",
                processor_version="baseline-v2",
                rotation_degrees=final_rotation,
                settings=settings,
            )
            now = datetime.now(UTC)
            project = db.get(ScanProject, page.project_id)
            if analysis is not None:
                page.ocr_text = analysis.text
                page.ocr_status = "ready"
                page.ocr_result_version = result.version
                page.ocr_model_version = analysis.model_version
                page.ocr_confidence = analysis.confidence
                page.ocr_rotation_degrees = analysis.rotation_degrees
                page.ocr_details = json.dumps(
                    analysis.details, ensure_ascii=False, sort_keys=True, separators=(",", ":")
                )
                page.ocr_title_candidate = analysis.title_candidate
                page.ocr_error_code = None
                page.ocr_updated_at = now
            else:
                page.ocr_text = None
                page.ocr_status = "disabled"
                page.ocr_result_version = None
                page.ocr_model_version = None
                page.ocr_confidence = None
                page.ocr_rotation_degrees = None
                page.ocr_details = None
                page.ocr_title_candidate = None
                page.ocr_error_code = None
                page.ocr_updated_at = now
            if exam_classification is not None:
                page.exam_classification_status = "ready"
                page.exam_result_version = result.version
                page.exam_classifier_version = exam_classification.classifier_version
                page.exam_prediction = exam_classification.prediction
                page.exam_probability = exam_classification.exam_probability
                page.exam_confidence_band = exam_classification.confidence_band
                page.exam_recommendation = exam_classification.recommendation
                page.exam_details = json.dumps(
                    exam_classification.details,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
                page.exam_suggestion_dismissed_result_version = None
                page.exam_suggestion_dismissed_by_user_id = None
                page.exam_suggestion_dismissed_at = None
                page.exam_suggestion_dismissal_reason = None
                page.exam_updated_at = now
            else:
                page.exam_classification_status = "disabled"
                page.exam_result_version = None
                page.exam_classifier_version = None
                page.exam_prediction = None
                page.exam_probability = None
                page.exam_confidence_band = None
                page.exam_recommendation = None
                page.exam_details = None
                page.exam_suggestion_dismissed_result_version = None
                page.exam_suggestion_dismissed_by_user_id = None
                page.exam_suggestion_dismissed_at = None
                page.exam_suggestion_dismissal_reason = None
                page.exam_updated_at = now
            if project is not None:
                candidate = analysis.title_candidate if analysis is not None else None
                if candidate and project.suggested_name_source != "ocr":
                    project.suggested_name = candidate
                    project.suggested_name_source = "ocr"
                    project.suggested_name_updated_at = now
                elif project.suggested_name is None:
                    project.suggested_name = default_document_name(locale, now.date())
                    project.suggested_name_source = "fallback"
                    project.suggested_name_updated_at = now
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


def process_project_cleanup_queue() -> bool:
    with SessionLocal() as db:
        result = process_next_project_cleanup(db, settings=settings)
        return result is not None


def process_upload_cleanup_queue() -> bool:
    with SessionLocal() as db:
        result = process_next_upload_cleanup(db, settings=settings)
        return result is not None


def main() -> None:
    ensure_database_current()
    if settings.ocr_enabled:
        get_ocr_engine()
    signal.signal(signal.SIGINT, stop)
    signal.signal(signal.SIGTERM, stop)
    next_deletion_sweep = 0.0
    while running:
        now_monotonic = time.monotonic()
        if now_monotonic >= next_deletion_sweep:
            try:
                process_upload_cleanup_queue()
                process_project_cleanup_queue()
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
