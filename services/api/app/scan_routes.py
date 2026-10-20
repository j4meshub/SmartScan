"""扫描项目、上传、文件与任务路由。"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Depends, File, Header, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import get_settings
from .database import get_db
from .dependencies import current_user
from .domain_services import (
    IMAGE_SUFFIXES,
    upload_has_expired,
    upload_matches_request,
    valid_image_signature,
)
from .models import (
    ProcessingJob,
    ScanPage,
    ScanProject,
    UploadChunk,
    UploadSession,
    UploadStatus,
    User,
)
from .policies import can_read_data
from .repositories import project_for_actor, upload_for_owner, upload_view
from .schemas import (
    ChunkReceipt,
    JobView,
    PageView,
    ProjectCreate,
    ProjectView,
    UploadCreate,
    UploadView,
)

settings = get_settings()
router = APIRouter()


@router.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    db.scalar(select(func.count()).select_from(User))
    return {"status": "ok", "ai_required": False, "time": datetime.now(UTC)}


@router.get("/v1/projects", response_model=list[ProjectView])
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ScanProject)
        .where(ScanProject.owner_user_id == user.id)
        .order_by(ScanProject.updated_at.desc())
    ).all()


@router.post("/v1/projects", response_model=ProjectView, status_code=201)
def create_project(
    payload: ProjectCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = ScanProject(owner_user_id=user.id, **payload.model_dump())
    db.add(project)
    db.commit()
    db.refresh(project)
    return project


@router.get("/v1/projects/{project_id}", response_model=ProjectView)
def get_project(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = project_for_actor(db, user, project_id)
    if project.owner_user_id != user.id:
        record_audit(
            db, request, user, "view_project", "project", project.id, project.owner_user_id
        )
        db.commit()
    return project


@router.get("/v1/projects/{project_id}/pages", response_model=list[PageView])
def list_pages(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = project_for_actor(db, user, project_id)
    if project.owner_user_id != user.id:
        record_audit(db, request, user, "view_pages", "project", project.id, project.owner_user_id)
        db.commit()
    return db.scalars(
        select(ScanPage).where(ScanPage.project_id == project.id).order_by(ScanPage.page_number)
    ).all()


@router.post("/v1/uploads", response_model=UploadView, status_code=201)
def create_upload(
    payload: UploadCreate,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = project_for_actor(db, user, payload.project_id)
    if project.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="project not found")
    if payload.size_bytes > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")

    safe_name = Path(payload.file_name).name.strip()
    if safe_name in ("", ".", ".."):
        raise HTTPException(status_code=422, detail="invalid file name")

    existing = db.scalar(
        select(UploadSession).where(
            UploadSession.owner_user_id == user.id,
            UploadSession.idempotency_key == payload.idempotency_key,
        )
    )
    if existing:
        if not upload_matches_request(existing, payload, safe_name):
            raise HTTPException(status_code=409, detail="idempotency key conflict")
        return upload_view(db, existing)

    chunk_size = min(settings.upload_chunk_bytes, payload.size_bytes)
    if chunk_size <= 0:
        raise HTTPException(status_code=500, detail="invalid server chunk configuration")
    upload = UploadSession(
        owner_user_id=user.id,
        project_id=project.id,
        idempotency_key=payload.idempotency_key,
        file_name=safe_name,
        mime_type=payload.mime_type,
        size_bytes=payload.size_bytes,
        expected_sha256=payload.sha256,
        chunk_size=chunk_size,
        total_chunks=math.ceil(payload.size_bytes / chunk_size),
        expires_at=datetime.now(UTC) + timedelta(hours=settings.upload_expiry_hours),
    )
    db.add(upload)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        existing = db.scalar(
            select(UploadSession).where(
                UploadSession.owner_user_id == user.id,
                UploadSession.idempotency_key == payload.idempotency_key,
            )
        )
        if existing and upload_matches_request(existing, payload, safe_name):
            return upload_view(db, existing)
        raise HTTPException(status_code=409, detail="idempotency key conflict") from None
    db.refresh(upload)
    return upload_view(db, upload)


@router.get("/v1/uploads/{upload_id}", response_model=UploadView)
def get_upload(
    upload_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    upload = upload_for_owner(db, user, upload_id)
    if upload.status == UploadStatus.pending and upload_has_expired(upload):
        upload.status = UploadStatus.expired
        db.commit()
    return upload_view(db, upload)


@router.put("/v1/uploads/{upload_id}/chunks/{chunk_index}", response_model=ChunkReceipt)
async def put_upload_chunk(
    upload_id: str,
    chunk_index: int,
    request: Request,
    x_chunk_sha256: str = Header(..., pattern=r"^[a-f0-9]{64}$"),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    upload = upload_for_owner(db, user, upload_id)
    if upload.status != UploadStatus.pending:
        raise HTTPException(status_code=409, detail="upload is not pending")
    if upload_has_expired(upload):
        upload.status = UploadStatus.expired
        db.commit()
        raise HTTPException(status_code=410, detail="upload expired")
    if chunk_index < 0 or chunk_index >= upload.total_chunks:
        raise HTTPException(status_code=416, detail="chunk index out of range")

    expected_size = min(upload.chunk_size, upload.size_bytes - chunk_index * upload.chunk_size)
    existing = db.scalar(
        select(UploadChunk).where(
            UploadChunk.upload_id == upload.id, UploadChunk.chunk_index == chunk_index
        )
    )
    if existing:
        if existing.sha256 != x_chunk_sha256 or existing.size_bytes != expected_size:
            raise HTTPException(status_code=409, detail="chunk already exists with other content")
        return ChunkReceipt(
            upload_id=upload.id,
            chunk_index=existing.chunk_index,
            size_bytes=existing.size_bytes,
            sha256=existing.sha256,
        )

    relative = Path("users") / user.id / "temp" / upload.id / f"{chunk_index:08d}.part"
    destination = settings.storage_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_suffix(".incoming")
    digest_builder = hashlib.sha256()
    received_size = 0
    exceeded_limit = False
    with incoming.open("wb") as output:
        async for block in request.stream():
            received_size += len(block)
            if received_size > expected_size:
                exceeded_limit = True
                break
            digest_builder.update(block)
            output.write(block)
    if exceeded_limit or received_size != expected_size:
        incoming.unlink(missing_ok=True)
        raise HTTPException(status_code=400, detail="unexpected chunk size")
    digest = digest_builder.hexdigest()
    if digest != x_chunk_sha256:
        incoming.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="chunk hash mismatch")
    os.replace(incoming, destination)
    chunk = UploadChunk(
        upload_id=upload.id,
        chunk_index=chunk_index,
        size_bytes=received_size,
        sha256=digest,
        relative_path=str(relative).replace("\\", "/"),
    )
    db.add(chunk)
    db.commit()
    return ChunkReceipt(
        upload_id=upload.id,
        chunk_index=chunk_index,
        size_bytes=received_size,
        sha256=digest,
    )


@router.post("/v1/uploads/{upload_id}/complete", response_model=PageView, status_code=202)
def complete_upload(
    upload_id: str,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    upload = upload_for_owner(db, user, upload_id, lock=True)
    if upload.status == UploadStatus.completed and upload.page_id:
        page = db.get(ScanPage, upload.page_id)
        if page:
            return page
    if upload.status != UploadStatus.pending:
        raise HTTPException(status_code=409, detail="upload is not pending")
    if upload_has_expired(upload):
        upload.status = UploadStatus.expired
        db.commit()
        raise HTTPException(status_code=410, detail="upload expired")

    chunks = db.scalars(
        select(UploadChunk)
        .where(UploadChunk.upload_id == upload.id)
        .order_by(UploadChunk.chunk_index)
    ).all()
    if len(chunks) != upload.total_chunks or [item.chunk_index for item in chunks] != list(
        range(upload.total_chunks)
    ):
        raise HTTPException(status_code=409, detail="upload has missing chunks")

    temp_dir = settings.storage_root / "users" / user.id / "temp" / upload.id
    assembled = temp_dir / "assembled.incoming"
    full_hash = hashlib.sha256()
    total_size = 0
    header = b""
    with assembled.open("wb") as output:
        for chunk in chunks:
            chunk_path = settings.storage_root / chunk.relative_path
            with chunk_path.open("rb") as source:
                while block := source.read(1024 * 1024):
                    if len(header) < 16:
                        header = (header + block)[:16]
                    total_size += len(block)
                    full_hash.update(block)
                    output.write(block)
    if total_size != upload.size_bytes or full_hash.hexdigest() != upload.expected_sha256:
        assembled.unlink(missing_ok=True)
        raise HTTPException(status_code=422, detail="completed file hash mismatch")
    if not valid_image_signature(upload.mime_type, header):
        assembled.unlink(missing_ok=True)
        raise HTTPException(status_code=415, detail="file signature does not match image type")

    project = db.get(ScanProject, upload.project_id)
    if not project or project.owner_user_id != user.id:
        assembled.unlink(missing_ok=True)
        raise HTTPException(status_code=404, detail="project not found")
    count = (
        db.scalar(
            select(func.count()).select_from(ScanPage).where(ScanPage.project_id == project.id)
        )
        or 0
    )
    page_id = str(uuid.uuid4())
    relative = (
        Path("users")
        / user.id
        / "originals"
        / project.id
        / (page_id + IMAGE_SUFFIXES[upload.mime_type])
    )
    destination = settings.storage_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(assembled, destination)
    page = ScanPage(
        id=page_id,
        project_id=project.id,
        owner_user_id=user.id,
        page_number=count + 1,
        original_path=str(relative).replace("\\", "/"),
        sha256=upload.expected_sha256,
        size_bytes=upload.size_bytes,
        mime_type=upload.mime_type,
    )
    db.add(page)
    db.flush()
    db.add(
        ProcessingJob(
            owner_user_id=user.id,
            project_id=project.id,
            page_id=page.id,
            kind=project.mode,
        )
    )
    upload.status = UploadStatus.completed
    upload.page_id = page.id
    db.commit()
    db.refresh(page)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return page


@router.post("/v1/projects/{project_id}/pages", response_model=PageView, status_code=202)
async def upload_page(
    project_id: str,
    file: UploadFile = File(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    project = project_for_actor(db, user, project_id)
    if project.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="project not found")
    if file.content_type not in IMAGE_SUFFIXES:
        raise HTTPException(status_code=415, detail="unsupported image type")
    data = await file.read(settings.max_upload_bytes + 1)
    if len(data) > settings.max_upload_bytes:
        raise HTTPException(status_code=413, detail="file too large")
    if len(data) < 16:
        raise HTTPException(status_code=400, detail="empty or invalid image")
    count = (
        db.scalar(
            select(func.count()).select_from(ScanPage).where(ScanPage.project_id == project.id)
        )
        or 0
    )
    page_id = str(uuid.uuid4())
    suffix = IMAGE_SUFFIXES[file.content_type]
    relative = Path("users") / user.id / "originals" / project.id / f"{page_id}{suffix}"
    destination = settings.storage_root / relative
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_bytes(data)
    page = ScanPage(
        id=page_id,
        project_id=project.id,
        owner_user_id=user.id,
        page_number=count + 1,
        original_path=str(relative).replace("\\", "/"),
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        mime_type=file.content_type,
    )
    db.add(page)
    db.add(
        ProcessingJob(
            owner_user_id=user.id, project_id=project.id, page_id=page.id, kind=project.mode
        )
    )
    db.commit()
    db.refresh(page)
    return page


@router.get("/v1/pages/{page_id}/content")
def page_content(
    page_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    page = db.get(ScanPage, page_id)
    if not page:
        raise HTTPException(status_code=404, detail="page not found")
    owner = db.get(User, page.owner_user_id)
    if not owner or not can_read_data(user, owner):
        raise HTTPException(status_code=404, detail="page not found")
    if page.owner_user_id != user.id:
        record_audit(db, request, user, "download_page", "page", page.id, page.owner_user_id)
        db.commit()
    relative = page.processed_path or page.original_path
    absolute = (settings.storage_root / relative).resolve()
    if settings.storage_root.resolve() not in absolute.parents:
        raise HTTPException(status_code=404, detail="page not found")
    return FileResponse(absolute, media_type=page.mime_type, filename=f"page-{page.page_number}")


@router.get("/v1/jobs", response_model=list[JobView])
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.owner_user_id == user.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(100)
    ).all()
