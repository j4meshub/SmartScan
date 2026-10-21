from __future__ import annotations

import os
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .config import Settings
from .models import JobStatus, ProcessingJob, UploadChunk, UploadSession, UploadStatus


class CapacityError(RuntimeError):
    def __init__(self, code: str, status_code: int) -> None:
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class StorageCapacity:
    total_bytes: int
    free_bytes: int
    reserved_upload_bytes: int
    required_free_bytes: int
    free_percent: float
    protected: bool


def _existing_storage_path(path: Path) -> Path:
    candidate = path.resolve(strict=False)
    while not candidate.exists():
        parent = candidate.parent
        if parent == candidate:
            raise CapacityError("storage_root_unavailable", 503)
        candidate = parent
    if not candidate.is_dir():
        raise CapacityError("storage_root_unavailable", 503)
    return candidate


def user_storage_bytes(storage_root: Path, user_id: str) -> int:
    root = storage_root.resolve(strict=False)
    user_root = (root / "users" / user_id).resolve(strict=False)
    try:
        user_root.relative_to(root)
    except ValueError as exc:
        raise CapacityError("storage_layout_unsafe", 503) from exc
    if not user_root.exists():
        return 0
    if user_root.is_symlink() or not user_root.is_dir():
        raise CapacityError("storage_layout_unsafe", 503)

    total = 0
    pending = [user_root]
    while pending:
        directory = pending.pop()
        with os.scandir(directory) as entries:
            for entry in entries:
                if entry.is_symlink():
                    raise CapacityError("storage_layout_unsafe", 503)
                if entry.is_dir(follow_symlinks=False):
                    pending.append(Path(entry.path))
                elif entry.is_file(follow_symlinks=False):
                    total += entry.stat(follow_symlinks=False).st_size
    return total


def lock_capacity(db: Session) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended('smartscan-storage-capacity', 0))")
        )


def pending_upload_bytes(
    db: Session,
    *,
    owner_user_id: str | None = None,
    now: datetime | None = None,
) -> int:
    now = now or datetime.now(UTC)
    chunk_totals = (
        select(
            UploadChunk.upload_id.label("upload_id"),
            func.sum(UploadChunk.size_bytes).label("received_bytes"),
        )
        .group_by(UploadChunk.upload_id)
        .subquery()
    )
    statement = (
        select(
            func.coalesce(
                func.sum(
                    UploadSession.size_bytes - func.coalesce(chunk_totals.c.received_bytes, 0)
                ),
                0,
            )
        )
        .outerjoin(chunk_totals, chunk_totals.c.upload_id == UploadSession.id)
        .where(
            UploadSession.status == UploadStatus.pending,
            UploadSession.expires_at > now,
        )
    )
    if owner_user_id is not None:
        statement = statement.where(UploadSession.owner_user_id == owner_user_id)
    return int(db.scalar(statement) or 0)


def storage_capacity(
    db: Session,
    settings: Settings,
    *,
    additional_bytes: int = 0,
) -> StorageCapacity:
    usage = shutil.disk_usage(_existing_storage_path(settings.storage_root))
    reserved = pending_upload_bytes(db)
    required = settings.storage_min_free_bytes + reserved + max(additional_bytes, 0)
    free_percent = (usage.free / usage.total * 100.0) if usage.total else 0.0
    return StorageCapacity(
        total_bytes=usage.total,
        free_bytes=usage.free,
        reserved_upload_bytes=reserved,
        required_free_bytes=required,
        free_percent=free_percent,
        protected=(usage.free < required or free_percent < settings.storage_min_free_percent),
    )


def ensure_new_upload_capacity(
    db: Session,
    settings: Settings,
    *,
    owner_user_id: str,
    size_bytes: int,
) -> StorageCapacity:
    lock_capacity(db)
    capacity = storage_capacity(db, settings, additional_bytes=size_bytes)
    if capacity.protected:
        raise CapacityError("storage_capacity_reached", 507)
    if settings.user_storage_quota_bytes:
        accounted = (
            user_storage_bytes(settings.storage_root, owner_user_id)
            + pending_upload_bytes(db, owner_user_id=owner_user_id)
            + size_bytes
        )
        if accounted > settings.user_storage_quota_bytes:
            raise CapacityError("user_storage_quota_reached", 413)
    return capacity


def ensure_reserved_upload_capacity(
    db: Session,
    settings: Settings,
    *,
    owner_user_id: str,
) -> StorageCapacity:
    capacity = storage_capacity(db, settings)
    if capacity.protected:
        raise CapacityError("storage_capacity_reached", 507)
    if settings.user_storage_quota_bytes:
        accounted = user_storage_bytes(settings.storage_root, owner_user_id) + pending_upload_bytes(
            db, owner_user_id=owner_user_id
        )
        if accounted > settings.user_storage_quota_bytes:
            raise CapacityError("user_storage_quota_reached", 413)
    return capacity


def ensure_assembly_capacity(
    db: Session,
    settings: Settings,
    *,
    size_bytes: int,
) -> StorageCapacity:
    capacity = storage_capacity(db, settings, additional_bytes=size_bytes)
    if capacity.protected:
        raise CapacityError("storage_capacity_reached", 507)
    return capacity


def active_job_count(db: Session) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.status.in_(
                    (
                        JobStatus.queued,
                        JobStatus.baseline_processing,
                        JobStatus.failed_retryable,
                        JobStatus.optional_enhancing,
                    )
                )
            )
        )
        or 0
    )


def ensure_queue_capacity(db: Session, settings: Settings) -> None:
    lock_capacity(db)
    if active_job_count(db) >= settings.queue_high_water_jobs:
        raise CapacityError("queue_capacity_reached", 429)


def worker_storage_ready(db: Session, settings: Settings) -> bool:
    try:
        return not storage_capacity(
            db,
            settings,
            additional_bytes=settings.max_upload_bytes,
        ).protected
    except (CapacityError, OSError):
        return False
