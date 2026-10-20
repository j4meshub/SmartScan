from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import record_audit
from .database import get_db
from .dependencies import current_user
from .identity_services import user_view
from .models import AuditLog, Role, ScanProject, SessionToken, User, UserStatus
from .policies import can_manage_account, can_read_data
from .schemas import ProjectView, RoleChange, StatusChange, UserView

router = APIRouter()


def require_admin(user: User) -> None:
    if user.role not in (Role.admin, Role.super_admin):
        raise HTTPException(status_code=403, detail="admin access required")
    if user.must_change_password:
        raise HTTPException(status_code=403, detail="password change required")


@router.get("/v1/admin/users", response_model=list[UserView])
def admin_users(user: User = Depends(current_user), db: Session = Depends(get_db)):
    require_admin(user)
    users = db.scalars(
        select(User).where(User.status != UserStatus.deleted).order_by(User.created_at.desc())
    ).all()
    return [user_view(db, item) for item in users]


@router.get("/v1/admin/users/{target_id}/projects", response_model=list[ProjectView])
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


@router.patch("/v1/admin/users/{target_id}/role", response_model=UserView)
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
    return user_view(db, target)


@router.patch("/v1/admin/users/{target_id}/status", response_model=UserView)
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
    return user_view(db, target)


@router.get("/v1/admin/audit")
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
