from __future__ import annotations

import json
import os
import signal
import socket
import time
import uuid
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
from services.worker.app.book import BookSplitResult, LogicalBookPage, split_book_spread
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


def _logical_book_image(page: LogicalBookPage) -> Image.Image:
    return page.dewarp.image if page.dewarp.applied else page.image


def _save_book_logical_source(
    *,
    image: Image.Image,
    owner_user_id: str,
    project_id: str,
    capture_id: str,
    side: str,
) -> tuple[str, Path]:
    relative = (
        Path("users") / owner_user_id / "book-logical" / project_id / capture_id / f"{side}.jpg"
    )
    destination = settings.storage_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.incoming")
    try:
        image.convert("RGB").save(incoming, "JPEG", quality=94, optimize=True)
        os.replace(incoming, destination)
    finally:
        incoming.unlink(missing_ok=True)
    return relative.as_posix(), destination


def _apply_book_metadata(
    page: ScanPage,
    metadata: dict[str, object],
    *,
    logical_source_path: str | None = None,
) -> None:
    page.book_capture_id = metadata.get("capture_id")  # type: ignore[assignment]
    page.book_side = metadata.get("side")  # type: ignore[assignment]
    page.book_split_status = str(metadata["split_status"])
    page.book_split_confidence = metadata.get("split_confidence")  # type: ignore[assignment]
    page.book_split_reason = metadata.get("split_reason")  # type: ignore[assignment]
    page.book_spine_x = metadata.get("spine_x")  # type: ignore[assignment]
    page.book_dewarp_applied = metadata.get("dewarp_applied")  # type: ignore[assignment]
    page.book_dewarp_source_score = metadata.get("dewarp_source_score")  # type: ignore[assignment]
    page.book_dewarp_output_score = metadata.get("dewarp_output_score")  # type: ignore[assignment]
    page.book_dewarp_reason = metadata.get("dewarp_reason")  # type: ignore[assignment]
    if logical_source_path is not None:
        page.book_logical_source_path = logical_source_path


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
    owner_user_id: str | None = None
    project_id: str | None = None
    book_capture_id: str | None = None
    book_side: str | None = None
    book_split_status = "disabled"
    book_metadata: dict[str, object] | None = None
    reading_order = "left_to_right"
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
            source = settings.storage_root / (page.book_logical_source_path or page.original_path)
            page_id = page.id
            job_kind = job.kind
            owner_user_id = job.owner_user_id
            project_id = job.project_id
            rotation_degrees = page.rotation_degrees
            book_capture_id = page.book_capture_id
            book_side = page.book_side
            book_split_status = page.book_split_status
            book_metadata = {
                "capture_id": page.book_capture_id,
                "side": page.book_side,
                "split_status": page.book_split_status,
                "split_confidence": page.book_split_confidence,
                "split_reason": page.book_split_reason,
                "spine_x": page.book_spine_x,
                "dewarp_applied": page.book_dewarp_applied,
                "dewarp_source_score": page.book_dewarp_source_score,
                "dewarp_output_score": page.book_dewarp_output_score,
                "dewarp_reason": page.book_dewarp_reason,
            }
            project = db.get(ScanProject, page.project_id)
            if project is not None and project.reading_order == "rtl":
                reading_order = "right_to_left"
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
    book_split_result: BookSplitResult | None = None
    book_logical_images: dict[str, Image.Image] = {}
    book_logical_sources: dict[str, tuple[str, Path]] = {}
    try:
        if not heartbeat(claim, 15):
            return
        assert source is not None and page_id is not None
        with Image.open(source) as raw:
            image = ImageOps.exif_transpose(raw).convert("RGB")
            if job_kind == "book" and book_split_status == "pending" and book_side is None:
                book_split_result = split_book_spread(image, reading_order=reading_order)
                selected = book_split_result.pages[0]
                if book_split_result.split_detected:
                    capture_id = book_capture_id or page_id
                    book_capture_id = capture_id
                    for logical_page in book_split_result.pages:
                        logical_image = _logical_book_image(logical_page)
                        book_logical_images[logical_page.side] = logical_image.copy()
                    image = _logical_book_image(selected).copy()
                    book_metadata = {
                        "capture_id": capture_id,
                        "side": selected.side,
                        "split_status": "split",
                        "split_confidence": book_split_result.confidence,
                        "split_reason": book_split_result.reason,
                        "spine_x": book_split_result.spine_x,
                        "dewarp_applied": selected.dewarp.applied,
                        "dewarp_source_score": selected.dewarp.source_score,
                        "dewarp_output_score": selected.dewarp.output_score,
                        "dewarp_reason": selected.dewarp.reason,
                    }
                else:
                    image = selected.image.copy()
                    book_metadata = {
                        "capture_id": book_capture_id or page_id,
                        "side": "single",
                        "split_status": "fallback",
                        "split_confidence": book_split_result.confidence,
                        "split_reason": book_split_result.reason,
                        "spine_x": None,
                        "dewarp_applied": selected.dewarp.applied,
                        "dewarp_source_score": selected.dewarp.source_score,
                        "dewarp_output_score": selected.dewarp.output_score,
                        "dewarp_reason": selected.dewarp.reason,
                    }
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
            if book_metadata is not None and book_split_status != "disabled":
                quality_details["book"] = book_metadata
                if book_metadata.get("split_status") == "fallback":
                    quality_warning_value = "book_split_review"
                    quality_score = min(quality_score, 70.0)
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
        if book_logical_images:
            assert (
                book_capture_id is not None and owner_user_id is not None and project_id is not None
            )
            for side, logical_image in book_logical_images.items():
                book_logical_sources[side] = _save_book_logical_source(
                    image=logical_image,
                    owner_user_id=owner_user_id,
                    project_id=project_id,
                    capture_id=book_capture_id,
                    side=side,
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
                for _, book_output in book_logical_sources.values():
                    book_output.unlink(missing_ok=True)
                return
            project = db.scalar(
                select(ScanProject).where(ScanProject.id == page.project_id).with_for_update()
            )
            if project is None:
                raise RuntimeError("project_missing")
            if book_split_result is not None and page.book_split_status == "pending":
                if book_split_result.split_detected:
                    first_page, second_page = book_split_result.pages
                    first_source = book_logical_sources[first_page.side][0]
                    second_source = book_logical_sources[second_page.side][0]
                    assert book_metadata is not None and book_capture_id is not None
                    _apply_book_metadata(
                        page,
                        book_metadata,
                        logical_source_path=first_source,
                    )
                    later_pages = list(
                        db.scalars(
                            select(ScanPage)
                            .where(
                                ScanPage.project_id == page.project_id,
                                ScanPage.page_number > page.page_number,
                            )
                            .order_by(ScanPage.page_number.desc(), ScanPage.id.desc())
                            .with_for_update()
                        )
                    )
                    for later_page in later_pages:
                        later_page.page_number += 1
                    second_metadata: dict[str, object] = {
                        "capture_id": book_capture_id,
                        "side": second_page.side,
                        "split_status": "split",
                        "split_confidence": book_split_result.confidence,
                        "split_reason": book_split_result.reason,
                        "spine_x": book_split_result.spine_x,
                        "dewarp_applied": second_page.dewarp.applied,
                        "dewarp_source_score": second_page.dewarp.source_score,
                        "dewarp_output_score": second_page.dewarp.output_score,
                        "dewarp_reason": second_page.dewarp.reason,
                    }
                    child = ScanPage(
                        id=str(uuid.uuid4()),
                        project_id=page.project_id,
                        owner_user_id=page.owner_user_id,
                        page_number=page.page_number + 1,
                        original_path=page.original_path,
                        original_mime_type=page.original_mime_type,
                        sha256=page.sha256,
                        size_bytes=page.size_bytes,
                        mime_type=page.mime_type,
                    )
                    _apply_book_metadata(
                        child,
                        second_metadata,
                        logical_source_path=second_source,
                    )
                    db.add(child)
                    db.flush()
                    db.add(
                        ProcessingJob(
                            owner_user_id=page.owner_user_id,
                            project_id=page.project_id,
                            page_id=child.id,
                            kind="book_logical",
                            max_attempts=settings.job_max_attempts,
                        )
                    )
                else:
                    assert book_metadata is not None
                    _apply_book_metadata(page, book_metadata)
                project.updated_at = datetime.now(UTC)
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
                result_type=(
                    "book_logical"
                    if job_kind in {"book", "book_logical", "book_retake"}
                    else "baseline"
                ),
                processor_version=(
                    "book-split-v1"
                    if job_kind in {"book", "book_logical", "book_retake"}
                    else "baseline-v2"
                ),
                rotation_degrees=final_rotation,
                settings=settings,
            )
            now = datetime.now(UTC)
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
        for _, book_output in book_logical_sources.values():
            book_output.unlink(missing_ok=True)
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
