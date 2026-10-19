from __future__ import annotations

import hashlib
import math
import os
import shutil
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import get_settings
from .database import Base, SessionLocal, engine, get_db
from .dependencies import current_user
from .models import (
    AuditLog,
    ProcessingJob,
    Role,
    ScanPage,
    ScanProject,
    SessionToken,
    UploadChunk,
    UploadSession,
    UploadStatus,
    User,
    UserIdentity,
    UserStatus,
)
from .policies import can_manage_account, can_read_data
from .schemas import (
    ChunkReceipt,
    JobView,
    LoginRequest,
    PageView,
    PasswordChange,
    ProjectCreate,
    ProjectView,
    RegisterRequest,
    RoleChange,
    StatusChange,
    TokenResponse,
    UploadCreate,
    UploadView,
    UserView,
)
from .security import (
    hash_password,
    mask_phone,
    new_session,
    phone_hmac,
    verify_password,
)

settings = get_settings()
IMAGE_SUFFIXES = {
    "image/jpeg": ".jpg",
    "image/png": ".png",
    "image/webp": ".webp",
    "image/heic": ".heic",
}


def ensure_superadmin(db: Session) -> None:
    existing = db.scalar(select(User).where(User.role == Role.super_admin))
    if existing or not settings.superadmin_password:
        return
    admin = User(
        username="admin",
        password_hash=hash_password(settings.superadmin_password),
        phone_hmac=hashlib.sha256(b"superadmin-no-phone").hexdigest(),
        phone_masked="not-bound",
        role=Role.super_admin,
        must_change_password=True,
    )
    db.add(admin)
    db.flush()
    db.add(UserIdentity(user_id=admin.id, provider="local", provider_subject="admin"))
    db.commit()


@asynccontextmanager
async def lifespan(_: FastAPI):
    Base.metadata.create_all(engine)
    with SessionLocal() as db:
        ensure_superadmin(db)
    yield


app = FastAPI(
    title="SmartScan API",
    version="0.1.0",
    description="Unified account, RBAC, scanning projects, uploads and CPU processing queue.",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.middleware("http")
async def request_id_middleware(request: Request, call_next):
    request.state.request_id = request.headers.get("x-request-id") or str(uuid.uuid4())
    response = await call_next(request)
    response.headers["x-request-id"] = request.state.request_id
    response.headers["x-content-type-options"] = "nosniff"
    response.headers["referrer-policy"] = "same-origin"
    return response


def issue_session(db: Session, user: User) -> TokenResponse:
    raw, digest, expires = new_session()
    db.add(SessionToken(user_id=user.id, token_hash=digest, expires_at=expires))
    db.commit()
    return TokenResponse(access_token=raw, expires_at=expires)


def project_for_actor(db: Session, actor: User, project_id: str) -> ScanProject:
    project = db.get(ScanProject, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="project not found")
    owner = db.get(User, project.owner_user_id)
    if not owner or not can_read_data(actor, owner):
        raise HTTPException(status_code=404, detail="project not found")
    return project


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


def upload_has_expired(upload: UploadSession) -> bool:
    expires_at = upload.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    return expires_at <= datetime.now(UTC)


def upload_matches_request(upload: UploadSession, payload: UploadCreate, safe_name: str) -> bool:
    return (
        upload.project_id == payload.project_id
        and upload.file_name == safe_name
        and upload.mime_type == payload.mime_type
        and upload.size_bytes == payload.size_bytes
        and upload.expected_sha256 == payload.sha256
    )


def valid_image_signature(mime_type: str, header: bytes) -> bool:
    if mime_type == "image/jpeg":
        return header.startswith(b"\xff\xd8\xff")
    if mime_type == "image/png":
        return header.startswith(b"\x89PNG\r\n\x1a\n")
    if mime_type == "image/webp":
        return header.startswith(b"RIFF") and header[8:12] == b"WEBP"
    if mime_type == "image/heic":
        return len(header) >= 12 and header[4:8] == b"ftyp"
    return False


@app.get("/health")
def health(db: Session = Depends(get_db)) -> dict[str, object]:
    db.scalar(select(func.count()).select_from(User))
    return {"status": "ok", "ai_required": False, "time": datetime.now(UTC)}


@app.post("/v1/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if settings.env != "development" or payload.sms_code != settings.dev_sms_code:
        raise HTTPException(status_code=400, detail="invalid verification code")
    digest = phone_hmac(payload.phone)
    existing_phone = db.scalar(select(User).where(User.phone_hmac == digest))
    existing_name = db.scalar(select(User).where(User.username == payload.username))
    if existing_name:
        raise HTTPException(status_code=409, detail="username already exists")
    if existing_phone:
        if existing_phone.status != UserStatus.active:
            raise HTTPException(status_code=403, detail="phone is linked to an unavailable account")
        raise HTTPException(status_code=409, detail="phone already registered; use account binding")
    try:
        password_hash = hash_password(payload.password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user = User(
        username=payload.username,
        password_hash=password_hash,
        phone_hmac=digest,
        phone_masked=mask_phone(payload.phone),
        locale=payload.locale if payload.locale in ("zh-CN", "en") else "zh-CN",
    )
    db.add(user)
    db.flush()
    db.add(UserIdentity(user_id=user.id, provider="local", provider_subject=payload.username))
    record_audit(db, request, user, "register", "user", user.id, user.id)
    return issue_session(db, user)


@app.post("/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    user = db.scalar(select(User).where(User.username == payload.username))
    if not user or not verify_password(payload.password, user.password_hash):
        record_audit(db, request, None, "login", "user", result="denied")
        db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user.status != UserStatus.active:
        raise HTTPException(status_code=403, detail="account unavailable")
    identity = db.scalar(
        select(UserIdentity).where(
            UserIdentity.user_id == user.id, UserIdentity.provider == "local"
        )
    )
    if identity:
        identity.last_login_at = datetime.now(UTC)
    record_audit(db, request, user, "login", "user", user.id, user.id)
    return issue_session(db, user)


@app.post("/v1/auth/logout", status_code=204)
def logout(
    authorization: str = Header(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    from .security import token_hash

    digest = token_hash(authorization.split(" ", 1)[1])
    token = db.scalar(select(SessionToken).where(SessionToken.token_hash == digest))
    if token:
        token.revoked_at = datetime.now(UTC)
        db.commit()


@app.get("/v1/me", response_model=UserView)
def me(user: User = Depends(current_user)):
    return user


@app.post("/v1/me/password", status_code=204)
def change_password(
    payload: PasswordChange,
    request: Request,
    authorization: str = Header(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    if not verify_password(payload.current_password, user.password_hash):
        raise HTTPException(status_code=400, detail="current password is incorrect")
    try:
        user.password_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    user.must_change_password = False
    from .security import token_hash

    current_digest = token_hash(authorization.split(" ", 1)[1])
    db.execute(
        update(SessionToken)
        .where(SessionToken.user_id == user.id, SessionToken.token_hash != current_digest)
        .values(revoked_at=datetime.now(UTC))
    )
    record_audit(db, request, user, "change_password", "user", user.id, user.id)
    db.commit()


@app.get("/v1/projects", response_model=list[ProjectView])
def list_projects(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ScanProject)
        .where(ScanProject.owner_user_id == user.id)
        .order_by(ScanProject.updated_at.desc())
    ).all()


@app.post("/v1/projects", response_model=ProjectView, status_code=201)
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


@app.get("/v1/projects/{project_id}", response_model=ProjectView)
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


@app.get("/v1/projects/{project_id}/pages", response_model=list[PageView])
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


@app.post("/v1/uploads", response_model=UploadView, status_code=201)
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


@app.get("/v1/uploads/{upload_id}", response_model=UploadView)
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


@app.put("/v1/uploads/{upload_id}/chunks/{chunk_index}", response_model=ChunkReceipt)
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


@app.post("/v1/uploads/{upload_id}/complete", response_model=PageView, status_code=202)
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


@app.post("/v1/projects/{project_id}/pages", response_model=PageView, status_code=202)
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


@app.get("/v1/pages/{page_id}/content")
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


@app.get("/v1/jobs", response_model=list[JobView])
def jobs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return db.scalars(
        select(ProcessingJob)
        .where(ProcessingJob.owner_user_id == user.id)
        .order_by(ProcessingJob.created_at.desc())
        .limit(100)
    ).all()


def require_admin(user: User) -> None:
    if user.role not in (Role.admin, Role.super_admin):
        raise HTTPException(status_code=403, detail="admin access required")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="password change required")


@app.get("/v1/admin/users", response_model=list[UserView])
def admin_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    return db.scalars(
        select(User).where(User.status != UserStatus.deleted).order_by(User.created_at.desc())
    ).all()


@app.get("/v1/admin/users/{target_id}/projects", response_model=list[ProjectView])
def admin_user_projects(
    target_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    target = db.get(User, target_id)
    if not target or not can_read_data(user, target):
        raise HTTPException(status_code=404, detail="user not found")
    record_audit(db, request, user, "view_user_projects", "user", target.id, target.id)
    projects = db.scalars(
        select(ScanProject)
        .where(ScanProject.owner_user_id == target.id)
        .order_by(ScanProject.updated_at.desc())
    ).all()
    db.commit()
    return projects


@app.patch("/v1/admin/users/{target_id}/role", response_model=UserView)
def change_role(
    target_id: str,
    payload: RoleChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    target = db.get(User, target_id)
    if not target or not can_manage_account(user, target) or payload.role == Role.super_admin:
        raise HTTPException(status_code=404, detail="user not found")
    target.role = payload.role
    db.execute(
        update(SessionToken)
        .where(SessionToken.user_id == target.id)
        .values(revoked_at=datetime.now(UTC))
    )
    record_audit(db, request, user, "change_role", "user", target.id, target.id)
    db.commit()
    db.refresh(target)
    return target


@app.patch("/v1/admin/users/{target_id}/status", response_model=UserView)
def change_status(
    target_id: str,
    payload: StatusChange,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user)
    target = db.get(User, target_id)
    if not target or not can_manage_account(user, target) or payload.status == UserStatus.deleted:
        raise HTTPException(status_code=404, detail="user not found")
    if payload.status not in (UserStatus.active, UserStatus.disabled):
        raise HTTPException(status_code=422, detail="unsupported status transition")
    target.status = payload.status
    db.execute(
        update(SessionToken)
        .where(SessionToken.user_id == target.id)
        .values(revoked_at=datetime.now(UTC))
    )
    record_audit(db, request, user, "change_status", "user", target.id, target.id)
    db.commit()
    db.refresh(target)
    return target


@app.get("/v1/admin/audit")
def audit_logs(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    rows = db.scalars(select(AuditLog).order_by(AuditLog.created_at.desc()).limit(200)).all()
    return [
        {
            "id": row.id,
            "actor_user_id": row.actor_user_id,
            "target_user_id": row.target_user_id,
            "object_type": row.object_type,
            "object_id": row.object_id,
            "action": row.action,
            "result": row.result,
            "created_at": row.created_at,
        }
        for row in rows
    ]
