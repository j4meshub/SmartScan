from __future__ import annotations

import hashlib
import uuid
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Depends, FastAPI, File, Header, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from sqlalchemy import func, select, update
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
    User,
    UserIdentity,
    UserStatus,
)
from .policies import can_manage_account, can_read_data
from .schemas import (
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
    if file.content_type not in ("image/jpeg", "image/png", "image/webp", "image/heic"):
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
    suffix = {
        "image/jpeg": ".jpg",
        "image/png": ".png",
        "image/webp": ".webp",
        "image/heic": ".heic",
    }[file.content_type]
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
