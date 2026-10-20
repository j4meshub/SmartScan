from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path

from sqlalchemy import delete, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import UploadChunk, UploadSession, UploadStatus


class UploadCleanupError(RuntimeError):
    pass


def cleanup_upload_chunks(
    db: Session,
    upload: UploadSession,
    *,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    chunks = list(db.scalars(select(UploadChunk).where(UploadChunk.upload_id == upload.id)))
    root = settings.storage_root.resolve()
    removed_ids: list[str] = []
    parents: set[Path] = set()
    complete = True
    for chunk in chunks:
        absolute = (root / chunk.relative_path).resolve()
        if root not in absolute.parents:
            raise UploadCleanupError("upload_file_path_invalid")
        try:
            absolute.unlink(missing_ok=True)
            removed_ids.append(chunk.id)
            parents.add(absolute.parent)
        except OSError:
            complete = False
    if removed_ids:
        db.execute(delete(UploadChunk).where(UploadChunk.id.in_(removed_ids)))
    db.commit()
    for parent in parents:
        try:
            parent.rmdir()
        except OSError:
            pass
    return complete


def process_next_upload_cleanup(
    db: Session,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> UploadSession | None:
    now = now or datetime.now(UTC)
    upload = db.scalar(
        select(UploadSession)
        .where(UploadSession.status == UploadStatus.pending, UploadSession.expires_at <= now)
        .order_by(UploadSession.expires_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if upload is None:
        upload = db.scalar(
            select(UploadSession)
            .join(UploadChunk)
            .where(UploadSession.status.in_((UploadStatus.expired, UploadStatus.canceled)))
            .order_by(UploadSession.updated_at)
            .limit(1)
            .with_for_update(skip_locked=True)
        )
    if upload is None:
        return None
    if upload.status == UploadStatus.pending:
        upload.status = UploadStatus.expired
        db.commit()
    cleanup_upload_chunks(db, upload, settings=settings)
    return upload
