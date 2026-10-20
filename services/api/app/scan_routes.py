"""扫描项目、上传、文件与任务路由。"""

from __future__ import annotations

import hashlib
import math
import os
import shutil
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import (
    APIRouter,
    Depends,
    File,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    UploadFile,
)
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
from .export_service import ExportError, create_export
from .file_delivery import attachment_response
from .job_service import JobFlowError, cancel_job, retry_job
from .models import (
    ExportArtifact,
    PageResult,
    ProcessingJob,
    ProjectDeletion,
    ScanExport,
    ScanPage,
    ScanProject,
    UploadChunk,
    UploadSession,
    UploadStatus,
    User,
)
from .page_service import (
    PageMutationError,
    page_for_owner,
    page_view,
    rotate_page,
    update_page_review,
)
from .policies import can_read_data
from .project_cleanup import (
    ProjectCleanupError,
    cleanup_project_files,
    start_project_deletion,
)
from .repositories import page_for_actor, project_for_actor, upload_for_owner, upload_view
from .schemas import (
    ChunkReceipt,
    ExportCreate,
    ExportView,
    JobView,
    PageResultView,
    PageReviewUpdate,
    PageRotationRequest,
    PageView,
    ProjectCreate,
    ProjectDeletionView,
    ProjectView,
    UploadCreate,
    UploadView,
)
from .upload_cleanup import UploadCleanupError, cleanup_upload_chunks

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


@router.delete("/v1/projects/{project_id}", response_model=ProjectDeletionView, status_code=202)
def delete_project(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanProject, project_id)
    if candidate is not None and candidate.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "delete_project",
            "project",
            project_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="project not found")
    project = project_for_actor(db, user, project_id)
    try:
        deletion = start_project_deletion(db, actor=user, project=project, settings=settings)
        record_audit(
            db, request, user, "delete_project", "project", project.id, project.owner_user_id
        )
        db.commit()
    except ProjectCleanupError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    return cleanup_project_files(db, deletion, settings=settings)


@router.get("/v1/project-deletions/{deletion_id}", response_model=ProjectDeletionView)
def get_project_deletion(
    deletion_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    deletion = db.get(ProjectDeletion, deletion_id)
    owner = db.get(User, deletion.owner_user_id) if deletion is not None else None
    if deletion is None or owner is None or not can_read_data(user, owner):
        raise HTTPException(status_code=404, detail="project deletion not found")
    if deletion.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "view_project_deletion",
            "project_deletion",
            deletion.id,
            deletion.owner_user_id,
        )
        db.commit()
    return deletion


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
    pages = db.scalars(
        select(ScanPage).where(ScanPage.project_id == project.id).order_by(ScanPage.page_number)
    ).all()
    return [page_view(db, page) for page in pages]


@router.get("/v1/projects/{project_id}/exports", response_model=list[ExportView])
def list_exports(
    project_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanProject, project_id)
    candidate_owner = db.get(User, candidate.owner_user_id) if candidate is not None else None
    if (
        candidate is not None
        and candidate_owner is not None
        and not can_read_data(user, candidate_owner)
    ):
        record_audit(
            db,
            request,
            user,
            "view_exports",
            "project",
            project_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="project not found")
    project = project_for_actor(db, user, project_id)
    if project.owner_user_id != user.id:
        record_audit(
            db, request, user, "view_exports", "project", project.id, project.owner_user_id
        )
        db.commit()
    return db.scalars(
        select(ScanExport)
        .where(ScanExport.project_id == project.id)
        .order_by(ScanExport.created_at.desc())
    ).all()


@router.post("/v1/projects/{project_id}/exports", response_model=ExportView, status_code=201)
def create_project_export(
    project_id: str,
    payload: ExportCreate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanProject, project_id)
    if candidate is not None and candidate.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "create_export",
            "project",
            project_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="project not found")
    project = project_for_actor(db, user, project_id)
    if project.owner_user_id != user.id:
        raise HTTPException(status_code=404, detail="project not found")
    try:
        return create_export(
            db,
            actor=user,
            project=project,
            format=payload.format,
            quality=payload.quality,
            include_ocr_text=payload.include_ocr_text,
            page_ids=payload.page_ids,
        )
    except ExportError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


@router.get("/v1/exports/{export_id}", response_model=ExportView)
def get_export(
    export_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    export = db.get(ScanExport, export_id)
    owner = db.get(User, export.owner_user_id) if export is not None else None
    if export is None or owner is None or not can_read_data(user, owner):
        if export is not None and owner is not None:
            record_audit(
                db,
                request,
                user,
                "view_export",
                "export",
                export.id,
                export.owner_user_id,
                "denied",
            )
            db.commit()
        raise HTTPException(status_code=404, detail="export not found")
    if export.owner_user_id != user.id:
        record_audit(db, request, user, "view_export", "export", export.id, export.owner_user_id)
        db.commit()
    return export


@router.get("/v1/export-artifacts/{artifact_id}/content")
def export_artifact_content(
    artifact_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    artifact = db.get(ExportArtifact, artifact_id)
    owner = db.get(User, artifact.owner_user_id) if artifact is not None else None
    if artifact is None or owner is None or not can_read_data(user, owner):
        if artifact is not None and owner is not None:
            record_audit(
                db,
                request,
                user,
                "download_export",
                "export_artifact",
                artifact.id,
                artifact.owner_user_id,
                "denied",
            )
            db.commit()
        raise HTTPException(status_code=404, detail="export artifact not found")
    absolute = (settings.storage_root / artifact.file_path).resolve()
    if settings.storage_root.resolve() not in absolute.parents or not absolute.is_file():
        raise HTTPException(status_code=404, detail="export artifact not found")
    record_audit(
        db,
        request,
        user,
        "download_export",
        "export_artifact",
        artifact.id,
        artifact.owner_user_id,
    )
    db.commit()
    return attachment_response(
        absolute=absolute,
        relative=artifact.file_path,
        media_type=artifact.mime_type,
        file_name=artifact.file_name,
        settings=settings,
        sha256=artifact.sha256,
    )


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


@router.delete("/v1/uploads/{upload_id}", status_code=204)
def cancel_upload(
    upload_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(UploadSession, upload_id)
    if candidate is not None and candidate.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "cancel_upload",
            "upload",
            upload_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="upload not found")
    upload = upload_for_owner(db, user, upload_id, lock=True)
    if upload.status == UploadStatus.completed:
        raise HTTPException(status_code=409, detail="completed upload cannot be canceled")
    if upload.status == UploadStatus.canceled:
        return Response(status_code=204)
    upload.status = UploadStatus.canceled
    record_audit(db, request, user, "cancel_upload", "upload", upload.id, upload.owner_user_id)
    db.commit()
    try:
        cleanup_upload_chunks(db, upload, settings=settings)
    except UploadCleanupError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    return Response(status_code=204)


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
            return page_view(db, page)
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
        original_mime_type=upload.mime_type,
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
            max_attempts=settings.job_max_attempts,
        )
    )
    upload.status = UploadStatus.completed
    upload.page_id = page.id
    db.commit()
    db.refresh(page)
    shutil.rmtree(temp_dir, ignore_errors=True)
    return page_view(db, page)


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
        original_mime_type=file.content_type,
        sha256=hashlib.sha256(data).hexdigest(),
        size_bytes=len(data),
        mime_type=file.content_type,
    )
    db.add(page)
    db.add(
        ProcessingJob(
            owner_user_id=user.id,
            project_id=project.id,
            page_id=page.id,
            kind=project.mode,
            max_attempts=settings.job_max_attempts,
        )
    )
    db.commit()
    db.refresh(page)
    return page_view(db, page)


@router.get("/v1/pages/{page_id}", response_model=PageView)
def get_page(
    page_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    page = page_for_actor(db, user, page_id)
    if page.owner_user_id != user.id:
        record_audit(db, request, user, "view_page", "page", page.id, page.owner_user_id)
        db.commit()
    return page_view(db, page)


@router.get("/v1/pages/{page_id}/results", response_model=list[PageResultView])
def page_results(
    page_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    page = page_for_actor(db, user, page_id)
    if page.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "view_page_results",
            "page",
            page.id,
            page.owner_user_id,
        )
        db.commit()
    return db.scalars(
        select(PageResult).where(PageResult.page_id == page.id).order_by(PageResult.version)
    ).all()


@router.post("/v1/pages/{page_id}/rotations", response_model=PageView)
def create_page_rotation(
    page_id: str,
    payload: PageRotationRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanPage, page_id)
    if candidate is not None and candidate.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "rotate_page",
            "page",
            page_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="page not found")
    destination = None
    try:
        page, destination = rotate_page(
            db,
            actor=user,
            page_id=page_id,
            degrees=payload.degrees,
            settings=settings,
        )
        record_audit(db, request, user, "rotate_page", "page", page.id, page.owner_user_id)
        db.commit()
    except PageMutationError as exc:
        db.rollback()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    except Exception:
        db.rollback()
        if destination is not None:
            destination.unlink(missing_ok=True)
        raise
    db.refresh(page)
    return page_view(db, page)


@router.patch("/v1/pages/{page_id}/review", response_model=PageView)
def change_page_review(
    page_id: str,
    payload: PageReviewUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanPage, page_id)
    if candidate is not None and candidate.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "change_page_review",
            "page",
            page_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="page not found")
    try:
        page = page_for_owner(db, user, page_id, lock=True)
    except PageMutationError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    update_page_review(
        page=page,
        actor=user,
        status=payload.status,
        note=payload.note,
    )
    record_audit(
        db,
        request,
        user,
        "change_page_review",
        "page",
        page.id,
        page.owner_user_id,
    )
    db.commit()
    db.refresh(page)
    return page_view(db, page)


@router.get("/v1/pages/{page_id}/content")
def page_content(
    page_id: str,
    request: Request,
    variant: str = Query(default="active", pattern=r"^(active|original)$"),
    version: int | None = Query(default=None, ge=1),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    page = page_for_actor(db, user, page_id)
    if page.owner_user_id != user.id:
        record_audit(db, request, user, "download_page", "page", page.id, page.owner_user_id)
        db.commit()
    result = None
    if version is not None:
        result = db.scalar(
            select(PageResult).where(
                PageResult.page_id == page.id,
                PageResult.version == version,
            )
        )
        if result is None:
            raise HTTPException(status_code=404, detail="page result not found")
    if variant == "original" and version is not None:
        raise HTTPException(status_code=422, detail="version cannot be used with original")
    relative = (
        page.original_path
        if variant == "original"
        else result.file_path
        if result is not None
        else page.processed_path or page.original_path
    )
    media_type = (
        page.original_mime_type
        if variant == "original"
        else result.mime_type
        if result is not None
        else page.mime_type
    )
    absolute = (settings.storage_root / relative).resolve()
    if settings.storage_root.resolve() not in absolute.parents or not absolute.is_file():
        raise HTTPException(status_code=404, detail="page not found")
    sha256 = page.sha256 if variant == "original" else result.sha256 if result else None
    return attachment_response(
        absolute=absolute,
        relative=relative,
        media_type=media_type,
        file_name=f"page-{page.page_number}",
        settings=settings,
        sha256=sha256,
    )


@router.get("/v1/jobs", response_model=list[JobView])
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.owner_user_id == user.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(100)
    ).all()


@router.get("/v1/jobs/{job_id}", response_model=JobView)
def get_job(
    job_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    job = db.get(ProcessingJob, job_id)
    owner = db.get(User, job.owner_user_id) if job is not None else None
    if job is None or owner is None or not can_read_data(user, owner):
        raise HTTPException(status_code=404, detail="job not found")
    if job.owner_user_id != user.id:
        record_audit(db, request, user, "view_job", "job", job.id, job.owner_user_id)
        db.commit()
    return job


def _deny_job_mutation(
    db: Session,
    request: Request,
    actor: User,
    *,
    job_id: str,
    action: str,
) -> None:
    candidate = db.get(ProcessingJob, job_id)
    if candidate is not None and candidate.owner_user_id != actor.id:
        record_audit(
            db,
            request,
            actor,
            action,
            "job",
            job_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="job not found")


@router.post("/v1/jobs/{job_id}/cancel", response_model=JobView)
def cancel_owned_job(
    job_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _deny_job_mutation(db, request, user, job_id=job_id, action="cancel_job")
    try:
        job = cancel_job(db, actor=user, job_id=job_id)
    except JobFlowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    record_audit(db, request, user, "cancel_job", "job", job.id, job.owner_user_id)
    db.commit()
    db.refresh(job)
    return job


@router.post("/v1/jobs/{job_id}/retry", response_model=JobView)
def retry_owned_job(
    job_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    _deny_job_mutation(db, request, user, job_id=job_id, action="retry_job")
    try:
        job = retry_job(db, actor=user, job_id=job_id)
    except JobFlowError as exc:
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    record_audit(db, request, user, "retry_job", "job", job.id, job.owner_user_id)
    db.commit()
    db.refresh(job)
    return job
