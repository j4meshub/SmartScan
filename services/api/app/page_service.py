from __future__ import annotations

import hashlib
import json
import os
import uuid
from datetime import UTC, datetime
from pathlib import Path

from PIL import Image, ImageOps
from sqlalchemy import select
from sqlalchemy.orm import Session

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
    active_job = db.scalar(
        select(ProcessingJob.id).where(
            ProcessingJob.page_id == page.id,
            ProcessingJob.status.in_([JobStatus.pending, JobStatus.running]),
        )
    )
    if active_job is not None:
        raise PageMutationError("page_processing_in_progress")
    active = active_page_result(db, page)
    source_relative = active.file_path if active is not None else page.original_path
    source = _safe_storage_path(settings, source_relative)
    if not source.is_file():
        raise PageMutationError("page_file_missing", status_code=404)
    cumulative_rotation = (page.rotation_degrees + degrees) % 360
    try:
        with Image.open(source) as raw:
            rotated = ImageOps.exif_transpose(raw).convert("RGB").rotate(-degrees, expand=True)
            _, destination = save_page_result(
                db,
                page=page,
                image=rotated,
                result_type="manual_rotation",
                processor_version="manual-v1",
                rotation_degrees=cumulative_rotation,
                settings=settings,
            )
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
