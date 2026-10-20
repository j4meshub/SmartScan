from __future__ import annotations

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import ScanPage, ScanProject, UploadChunk, UploadSession, User
from .policies import can_read_data
from .schemas import UploadView


def project_for_actor(db: Session, actor: User, project_id: str) -> ScanProject:
    project = db.get(ScanProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    owner = db.get(User, project.owner_user_id)
    if not owner or not can_read_data(actor, owner):
        raise HTTPException(status_code=404, detail="project not found")
    return project


def page_for_actor(db: Session, actor: User, page_id: str) -> ScanPage:
    page = db.get(ScanPage, page_id)
    if page is None:
        raise HTTPException(status_code=404, detail="page not found")
    owner = db.get(User, page.owner_user_id)
    if owner is None or not can_read_data(actor, owner):
        raise HTTPException(status_code=404, detail="page not found")
    return page


def upload_for_owner(db: Session, actor: User, upload_id: str, lock: bool = False) -> UploadSession:
    statement = select(UploadSession).where(
        UploadSession.id == upload_id, UploadSession.owner_user_id == actor.id
    )
    if lock:
        statement = statement.with_for_update()
    upload = db.scalar(statement)
    if not upload:
        raise HTTPException(status_code=404, detail="upload not found")
    return upload


def upload_view(db: Session, upload: UploadSession) -> UploadView:
    received = db.scalars(
        select(UploadChunk.chunk_index)
        .where(UploadChunk.upload_id == upload.id)
        .order_by(UploadChunk.chunk_index)
    ).all()
    return UploadView(
        id=upload.id,
        project_id=upload.project_id,
        file_name=upload.file_name,
        mime_type=upload.mime_type,
        size_bytes=upload.size_bytes,
        chunk_size=upload.chunk_size,
        total_chunks=upload.total_chunks,
        received_chunks=list(received),
        status=upload.status,
        page_id=upload.page_id,
        expires_at=upload.expires_at,
    )
