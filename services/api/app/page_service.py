from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageEnhance, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.worker.app.book_integrity import image_dhash

from .config import Settings, get_settings
from .models import (
    JobStatus,
    PageResult,
    PageReviewStatus,
    ProcessingJob,
    ScanPage,
    User,
)
from .schemas import PageView


class PageMutationError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _safe_storage_path(settings: Settings, relative: str) -> Path:
    root = settings.storage_root.resolve()
    absolute = (root / relative).resolve()
    if root not in absolute.parents:
        raise PageMutationError("page_file_path_invalid", status_code=500)
    return absolute


def active_page_result(db: Session, page: ScanPage) -> PageResult | None:
    if page.active_result_version <= 0:
        return None
    return db.scalar(
        select(PageResult).where(
            PageResult.page_id == page.id,
            PageResult.version == page.active_result_version,
        )
    )


def page_view(db: Session, page: ScanPage) -> PageView:
    details = None
    if page.quality_details:
        try:
            loaded = json.loads(page.quality_details)
            details = loaded if isinstance(loaded, dict) else None
        except json.JSONDecodeError:
            details = None
    ocr_details = None
    if page.ocr_details and page.ocr_result_version == page.active_result_version:
        try:
            loaded_ocr = json.loads(page.ocr_details)
            ocr_details = loaded_ocr if isinstance(loaded_ocr, dict) else None
        except json.JSONDecodeError:
            ocr_details = None
    ocr_is_current = page.ocr_result_version == page.active_result_version
    exam_details = None
    exam_is_current = page.exam_result_version == page.active_result_version
    if page.exam_details and exam_is_current:
        try:
            loaded_exam = json.loads(page.exam_details)
            exam_details = loaded_exam if isinstance(loaded_exam, dict) else None
        except json.JSONDecodeError:
            exam_details = None
    exam_dismissed = (
        page.exam_suggestion_dismissed_result_version == page.exam_result_version
        and page.exam_result_version is not None
    )
    exam_suggestion_visible = (
        exam_is_current
        and page.exam_recommendation in {"ask", "suggest_cleanup"}
        and not exam_dismissed
    )
    return PageView(
        id=page.id,
        project_id=page.project_id,
        page_number=page.page_number,
        size_bytes=page.size_bytes,
        mime_type=page.mime_type,
        original_mime_type=page.original_mime_type,
        quality_warning=page.quality_warning,
        quality_score=page.quality_score,
        quality_details=details,
        rotation_degrees=page.rotation_degrees,
        active_result_version=page.active_result_version,
        review_status=page.review_status,
        review_reason=page.review_reason,
        reviewed_by_user_id=page.reviewed_by_user_id,
        reviewed_at=page.reviewed_at,
        ocr_text=page.ocr_text if ocr_is_current else None,
        ocr_status=page.ocr_status,
        ocr_result_version=page.ocr_result_version,
        ocr_model_version=page.ocr_model_version if ocr_is_current else None,
        ocr_confidence=page.ocr_confidence if ocr_is_current else None,
        ocr_rotation_degrees=page.ocr_rotation_degrees if ocr_is_current else None,
        ocr_details=ocr_details,
        ocr_title_candidate=page.ocr_title_candidate if ocr_is_current else None,
        ocr_error_code=page.ocr_error_code,
        ocr_updated_at=page.ocr_updated_at,
        exam_classification_status=page.exam_classification_status,
        exam_result_version=page.exam_result_version,
        exam_classifier_version=page.exam_classifier_version if exam_is_current else None,
        exam_prediction=page.exam_prediction if exam_is_current else None,
        exam_probability=page.exam_probability if exam_is_current else None,
        exam_confidence_band=page.exam_confidence_band if exam_is_current else None,
        exam_recommendation=page.exam_recommendation if exam_is_current else None,
        exam_details=exam_details,
        exam_suggestion_visible=exam_suggestion_visible,
        exam_suggestion_dismissed_result_version=(
            page.exam_suggestion_dismissed_result_version if exam_dismissed else None
        ),
        exam_suggestion_dismissed_by_user_id=(
            page.exam_suggestion_dismissed_by_user_id if exam_dismissed else None
        ),
        exam_suggestion_dismissed_at=page.exam_suggestion_dismissed_at if exam_dismissed else None,
        exam_suggestion_dismissal_reason=(
            page.exam_suggestion_dismissal_reason if exam_dismissed else None
        ),
        exam_updated_at=page.exam_updated_at,
        book_capture_id=page.book_capture_id,
        book_side=page.book_side,
        book_split_status=page.book_split_status,
        book_split_confidence=page.book_split_confidence,
        book_split_reason=page.book_split_reason,
        book_spine_x=page.book_spine_x,
        book_dewarp_applied=page.book_dewarp_applied,
        book_dewarp_source_score=page.book_dewarp_source_score,
        book_dewarp_output_score=page.book_dewarp_output_score,
        book_dewarp_reason=page.book_dewarp_reason,
        book_replaced_by_page_id=page.book_replaced_by_page_id,
        book_is_current=page.book_replaced_by_page_id is None,
        book_page_number_status=page.book_page_number_status,
        book_page_number_label=(
            page.book_page_number_label
            if page.book_page_number_result_version == page.active_result_version
            else None
        ),
        book_page_number_value=(
            page.book_page_number_value
            if page.book_page_number_result_version == page.active_result_version
            else None
        ),
        book_page_number_kind=(
            page.book_page_number_kind
            if page.book_page_number_result_version == page.active_result_version
            else None
        ),
        book_page_number_confidence=(
            page.book_page_number_confidence
            if page.book_page_number_result_version == page.active_result_version
            else None
        ),
        book_page_number_reason=page.book_page_number_reason,
        book_page_number_result_version=page.book_page_number_result_version,
        book_expected_page_label=page.book_expected_page_label,
        book_content_fingerprint=(
            page.book_content_fingerprint
            if page.book_fingerprint_result_version == page.active_result_version
            else None
        ),
        book_fingerprint_result_version=page.book_fingerprint_result_version,
        book_assembly_included=page.book_assembly_included,
        book_assembly_exclusion_reason=page.book_assembly_exclusion_reason,
        active_result=active_page_result(db, page),
        created_at=page.created_at,
        updated_at=page.updated_at,
    )


def page_for_owner(db: Session, actor: User, page_id: str, *, lock: bool = False) -> ScanPage:
    statement = select(ScanPage).where(
        ScanPage.id == page_id,
        ScanPage.owner_user_id == actor.id,
    )
    if lock:
        statement = statement.with_for_update()
    page = db.scalar(statement)
    if page is None:
        raise PageMutationError("page_not_found", status_code=404)
    return page


def _ensure_page_mutable(db: Session, page: ScanPage) -> None:
    active_job = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.page_id == page.id,
            ProcessingJob.status.in_(
                [
                    JobStatus.queued,
                    JobStatus.baseline_processing,
                    JobStatus.baseline_ready,
                    JobStatus.optional_enhancing,
                    JobStatus.failed_retryable,
                ]
            ),
        )
    )
    if active_job is not None:
        raise PageMutationError("page_processing_in_progress")


def _invalidate_ocr(page: ScanPage) -> None:
    page.ocr_status = "stale"
    page.ocr_result_version = None
    page.ocr_text = None
    page.ocr_model_version = None
    page.ocr_confidence = None
    page.ocr_rotation_degrees = None
    page.ocr_details = None
    page.ocr_title_candidate = None
    page.ocr_error_code = None
    page.ocr_updated_at = datetime.now(UTC)


def _invalidate_book_integrity(page: ScanPage) -> None:
    if page.book_split_status == "disabled":
        return
    page.book_page_number_status = "stale"
    page.book_page_number_label = None
    page.book_page_number_value = None
    page.book_page_number_kind = None
    page.book_page_number_confidence = None
    page.book_page_number_reason = "page_result_changed"
    page.book_page_number_result_version = None
    page.book_content_fingerprint = None
    page.book_fingerprint_result_version = None


def _invalidate_exam_classification(page: ScanPage) -> None:
    page.exam_classification_status = "stale"
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
    page.exam_updated_at = datetime.now(UTC)


def _perspective_crop(
    image: Image.Image,
    corners: list[tuple[float, float]],
) -> Image.Image:
    if len(corners) != 4:
        raise PageMutationError("page_corners_invalid", status_code=422)
    width, height = image.size
    points = [(x * width, y * height) for x, y in corners]
    crosses = []
    for index in range(4):
        current = points[index]
        following = points[(index + 1) % 4]
        after = points[(index + 2) % 4]
        crosses.append(
            (following[0] - current[0]) * (after[1] - following[1])
            - (following[1] - current[1]) * (after[0] - following[0])
        )
    area = abs(
        sum(
            points[index][0] * points[(index + 1) % 4][1]
            - points[(index + 1) % 4][0] * points[index][1]
            for index in range(4)
        )
        / 2
    )
    if not (all(value > 0 for value in crosses) or all(value < 0 for value in crosses)):
        raise PageMutationError("page_corners_invalid", status_code=422)
    if area < width * height * 0.02:
        raise PageMutationError("page_corners_too_small", status_code=422)

    top_left, top_right, bottom_right, bottom_left = points

    def distance(first: tuple[float, float], second: tuple[float, float]) -> float:
        return ((first[0] - second[0]) ** 2 + (first[1] - second[1]) ** 2) ** 0.5

    output_width = round(max(distance(top_left, top_right), distance(bottom_left, bottom_right)))
    output_height = round(max(distance(top_left, bottom_left), distance(top_right, bottom_right)))
    if output_width < 32 or output_height < 32:
        raise PageMutationError("page_corners_too_small", status_code=422)
    return image.transform(
        (output_width, output_height),
        Image.Transform.QUAD,
        data=(
            *top_left,
            *bottom_left,
            *bottom_right,
            *top_right,
        ),
        resample=Image.Resampling.BICUBIC,
    )


def _apply_filter(image: Image.Image, filter_name: str) -> Image.Image:
    if filter_name == "original":
        return image.convert("RGB")
    if filter_name == "enhance":
        contrasted = ImageOps.autocontrast(image.convert("RGB"), cutoff=1)
        return ImageEnhance.Sharpness(contrasted).enhance(1.25)
    gray = ImageOps.autocontrast(image.convert("L"), cutoff=1)
    if filter_name == "grayscale":
        return gray.convert("RGB")
    if filter_name == "bw":
        return gray.point(lambda value: 255 if value >= 180 else 0).convert("RGB")
    raise PageMutationError("page_filter_invalid", status_code=422)


def edit_page(
    db: Session,
    *,
    actor: User,
    page_id: str,
    corners: list[tuple[float, float]] | None,
    filter_name: str,
    settings: Settings | None = None,
) -> tuple[ScanPage, Path]:
    settings = settings or get_settings()
    page = page_for_owner(db, actor, page_id, lock=True)
    _ensure_page_mutable(db, page)
    active = active_page_result(db, page)
    source_relative = active.file_path if active is not None else page.original_path
    source = _safe_storage_path(settings, source_relative)
    if not source.is_file():
        raise PageMutationError("page_file_missing", status_code=404)
    try:
        with Image.open(source) as raw:
            edited = ImageOps.exif_transpose(raw).convert("RGB")
            if corners is not None:
                edited = _perspective_crop(edited, corners)
            edited = _apply_filter(edited, filter_name)
            result, destination = save_page_result(
                db,
                page=page,
                image=edited,
                result_type="manual_edit",
                processor_version="manual-v1",
                rotation_degrees=page.rotation_degrees,
                settings=settings,
            )
            _invalidate_ocr(page)
            _invalidate_exam_classification(page)
            _invalidate_book_integrity(page)
            if page.book_split_status != "disabled":
                page.book_content_fingerprint = image_dhash(edited)
                page.book_fingerprint_result_version = result.version
    except PageMutationError:
        raise
    except Exception as exc:
        raise PageMutationError("page_edit_failed", status_code=422) from exc
    return page, destination


def save_page_result(
    db: Session,
    *,
    page: ScanPage,
    image: Image.Image,
    result_type: str,
    processor_version: str,
    rotation_degrees: int,
    settings: Settings | None = None,
) -> tuple[PageResult, Path]:
    settings = settings or get_settings()
    version = page.active_result_version + 1
    relative = (
        Path("users")
        / page.owner_user_id
        / "results"
        / page.project_id
        / page.id
        / f"v{version:04d}.jpg"
    )
    destination = _safe_storage_path(settings, str(relative))
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_name(f".{destination.name}.{uuid.uuid4().hex}.incoming")
    try:
        image.convert("RGB").save(incoming, "JPEG", quality=92, optimize=True)
        payload = incoming.read_bytes()
        os.replace(incoming, destination)
    finally:
        incoming.unlink(missing_ok=True)
    result = PageResult(
        page_id=page.id,
        owner_user_id=page.owner_user_id,
        version=version,
        result_type=result_type,
        file_path=str(relative).replace("\\", "/"),
        mime_type="image/jpeg",
        sha256=hashlib.sha256(payload).hexdigest(),
        size_bytes=len(payload),
        rotation_degrees=rotation_degrees,
        processor_version=processor_version,
    )
    db.add(result)
    page.processed_path = result.file_path
    page.mime_type = result.mime_type
    page.rotation_degrees = rotation_degrees
    page.active_result_version = version
    return result, destination


def rotate_page(
    db: Session,
    *,
    actor: User,
    page_id: str,
    degrees: int,
    settings: Settings | None = None,
) -> tuple[ScanPage, Path]:
    settings = settings or get_settings()
    page = page_for_owner(db, actor, page_id, lock=True)
    _ensure_page_mutable(db, page)
    active = active_page_result(db, page)
    source_relative = active.file_path if active is not None else page.original_path
    source = _safe_storage_path(settings, source_relative)
    if not source.is_file():
        raise PageMutationError("page_file_missing", status_code=404)
    cumulative_rotation = (page.rotation_degrees + degrees) % 360
    try:
        with Image.open(source) as raw:
            rotated = ImageOps.exif_transpose(raw).convert("RGB").rotate(-degrees, expand=True)
            result, destination = save_page_result(
                db,
                page=page,
                image=rotated,
                result_type="manual_rotation",
                processor_version="manual-v1",
                rotation_degrees=cumulative_rotation,
                settings=settings,
            )
            _invalidate_ocr(page)
            _invalidate_exam_classification(page)
            _invalidate_book_integrity(page)
            if page.book_split_status != "disabled":
                page.book_content_fingerprint = image_dhash(rotated)
                page.book_fingerprint_result_version = result.version
    except PageMutationError:
        raise
    except Exception as exc:
        raise PageMutationError("page_rotation_failed", status_code=422) from exc
    return page, destination


def update_page_review(
    *,
    page: ScanPage,
    actor: User,
    status: str,
    note: str | None,
) -> None:
    if status == "confirmed":
        page.review_status = PageReviewStatus.confirmed
        page.reviewed_by_user_id = actor.id
        page.reviewed_at = datetime.now(UTC)
    else:
        page.review_status = PageReviewStatus.pending
        page.reviewed_by_user_id = None
        page.reviewed_at = None
    page.review_reason = note or page.quality_warning


def dismiss_exam_suggestion(
    *,
    page: ScanPage,
    actor: User,
    result_version: int,
    reason: str | None,
) -> None:
    if (
        page.exam_classification_status != "ready"
        or page.exam_result_version != page.active_result_version
        or page.exam_result_version != result_version
        or page.exam_recommendation not in {"ask", "suggest_cleanup"}
    ):
        raise PageMutationError("exam_suggestion_not_current")
    page.exam_suggestion_dismissed_result_version = result_version
    page.exam_suggestion_dismissed_by_user_id = actor.id
    page.exam_suggestion_dismissed_at = datetime.now(UTC)
    page.exam_suggestion_dismissal_reason = reason
