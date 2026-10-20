from __future__ import annotations

import hmac
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Query, Request, Response
from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .account_deletion import (
    AccountDeletionError,
    cancel_account_deletion_by_admin,
    request_admin_account_deletion,
)
from .audit import record_audit
from .database import get_db
from .dependencies import current_user
from .identity_services import user_view
from .models import (
    AccountDeletionRequest,
    AccountDeletionStatus,
    AuditLog,
    Role,
    ScanProject,
    User,
    UserStatus,
)
from .policies import can_manage_account, can_read_data
from .schemas import (
    AdminAccountDeletionCancelPayload,
    AdminAccountDeletionRequestPayload,
    AdminAccountDeletionView,
    AuditLogView,
    ProjectView,
    RoleChange,
    StatusChange,
    UserView,
)
from .session_service import revoke_user_sessions

router = APIRouter()


def require_admin(
    user: User,
    request: Request,
    db: Session,
    *,
    action: str,
) -> None:
    detail = None
    if user.role not in (Role.admin, Role.super_admin):
        detail = "admin access required"
    elif user.must_change_password:
        detail = "password change required"
    if detail is not None:
        record_audit(db, request, user, action, "admin_endpoint", result="denied")
        db.commit()
        raise HTTPException(status_code=403, detail=detail)


def _deny_target(
    db: Session,
    request: Request,
    actor: User,
    *,
    action: str,
    target_id: str,
) -> None:
    record_audit(db, request, actor, action, "user", target_id, result="denied")
    db.commit()
    raise HTTPException(status_code=404, detail="user not found")


def _manageable_target(
    db: Session,
    request: Request,
    actor: User,
    target_id: str,
    *,
    action: str,
) -> User:
    target = db.get(User, target_id)
    if target is None or not can_manage_account(actor, target):
        _deny_target(db, request, actor, action=action, target_id=target_id)
    return target


def _deletion_view(deletion: AccountDeletionRequest, target: User) -> AdminAccountDeletionView:
    return AdminAccountDeletionView(
        id=deletion.id,
        user_id=deletion.user_id,
        username=target.username,
        status=deletion.status,
        request_source=deletion.request_source,
        requested_by_user_id=deletion.requested_by_user_id,
        reason=deletion.reason,
        cancellation_reason=deletion.cancellation_reason,
        requested_at=deletion.requested_at,
        execute_after=deletion.execute_after,
        canceled_at=deletion.canceled_at,
        completed_at=deletion.completed_at,
        attempts=deletion.attempts,
        last_error=deletion.last_error,
    )


@router.get("/v1/admin/users", response_model=list[UserView])
def admin_users(
    request: Request,
    response: Response,
    role: Role | None = Query(default=None),
    status_filter: UserStatus | None = Query(default=None, alias="status"),
    q: str | None = Query(default=None, min_length=1, max_length=64),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="list_users")
    conditions = [User.status != UserStatus.deleted]
    if user.role == Role.admin:
        conditions.append(User.role == Role.user)
    if role is not None:
        conditions.append(User.role == role)
    if status_filter is not None:
        conditions.append(User.status == status_filter)
    if q:
        pattern = f"%{q}%"
        conditions.append(or_(User.username.ilike(pattern), User.phone_masked.ilike(pattern)))
    total = db.scalar(select(func.count()).select_from(User).where(*conditions)) or 0
    users = db.scalars(
        select(User)
        .where(*conditions)
        .order_by(User.created_at.desc(), User.id)
        .offset(offset)
        .limit(limit)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    record_audit(db, request, user, "list_users", "user")
    db.commit()
    return [user_view(db, item) for item in users]


@router.get("/v1/admin/users/{target_id}/projects", response_model=list[ProjectView])
def admin_user_projects(
    target_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="view_user_projects")
    target = db.get(User, target_id)
    if not target or not can_read_data(user, target):
        _deny_target(
            db,
            request,
            user,
            action="view_user_projects",
            target_id=target_id,
        )
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
    require_admin(user, request, db, action="change_role")
    target = _manageable_target(db, request, user, target_id, action="change_role")
    if user.role != Role.super_admin or payload.role == Role.super_admin:
        _deny_target(db, request, user, action="change_role", target_id=target_id)
    target.role = payload.role
    revoke_user_sessions(db, target.id)
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
    require_admin(user, request, db, action="change_status")
    target = _manageable_target(db, request, user, target_id, action="change_status")
    if target.status not in (UserStatus.active, UserStatus.disabled):
        record_audit(db, request, user, "change_status", "user", target.id, target.id, "denied")
        db.commit()
        raise HTTPException(status_code=409, detail="account state transition unavailable")
    if payload.status not in (UserStatus.active, UserStatus.disabled):
        record_audit(db, request, user, "change_status", "user", target.id, target.id, "denied")
        db.commit()
        raise HTTPException(status_code=422, detail="unsupported status transition")
    target.status = payload.status
    revoke_user_sessions(db, target.id)
    record_audit(db, request, user, "change_status", "user", target.id, target.id)
    db.commit()
    db.refresh(target)
    return user_view(db, target)


@router.delete("/v1/admin/users/{target_id}/sessions", status_code=204)
def revoke_target_sessions(
    target_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="revoke_user_sessions")
    target = _manageable_target(db, request, user, target_id, action="revoke_user_sessions")
    revoke_user_sessions(db, target.id)
    record_audit(db, request, user, "revoke_user_sessions", "user", target.id, target.id)
    db.commit()


@router.post(
    "/v1/admin/users/{target_id}/account-deletion",
    response_model=AdminAccountDeletionView,
    status_code=202,
)
def create_admin_account_deletion(
    target_id: str,
    payload: AdminAccountDeletionRequestPayload,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="admin_request_account_deletion")
    target = _manageable_target(
        db,
        request,
        user,
        target_id,
        action="admin_request_account_deletion",
    )
    if not hmac.compare_digest(payload.confirm_username, target.username):
        record_audit(
            db,
            request,
            user,
            "admin_request_account_deletion",
            "user",
            target.id,
            target.id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=409, detail="account deletion confirmation mismatch")
    try:
        deletion = request_admin_account_deletion(
            db,
            actor=user,
            target=target,
            reason=payload.reason,
        )
    except AccountDeletionError as exc:
        record_audit(
            db,
            request,
            user,
            "admin_request_account_deletion",
            "user",
            target.id,
            target.id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    record_audit(
        db,
        request,
        user,
        "admin_request_account_deletion",
        "account_deletion",
        deletion.id,
        target.id,
    )
    db.commit()
    return _deletion_view(deletion, target)


@router.get(
    "/v1/admin/account-deletions",
    response_model=list[AdminAccountDeletionView],
)
def admin_account_deletions(
    request: Request,
    response: Response,
    status_filter: AccountDeletionStatus | None = Query(default=None, alias="status"),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="list_account_deletions")
    conditions = []
    if user.role == Role.admin:
        conditions.append(User.role == Role.user)
    if status_filter is not None:
        conditions.append(AccountDeletionRequest.status == status_filter)
    total = (
        db.scalar(
            select(func.count())
            .select_from(AccountDeletionRequest)
            .join(User, User.id == AccountDeletionRequest.user_id)
            .where(*conditions)
        )
        or 0
    )
    rows = db.execute(
        select(AccountDeletionRequest, User)
        .join(User, User.id == AccountDeletionRequest.user_id)
        .where(*conditions)
        .order_by(AccountDeletionRequest.requested_at.desc())
        .offset(offset)
        .limit(limit)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    record_audit(db, request, user, "list_account_deletions", "account_deletion")
    db.commit()
    return [_deletion_view(deletion, target) for deletion, target in rows]


@router.post(
    "/v1/admin/account-deletions/{request_id}/cancel",
    response_model=AdminAccountDeletionView,
)
def cancel_admin_account_deletion(
    request_id: str,
    payload: AdminAccountDeletionCancelPayload,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="admin_cancel_account_deletion")
    deletion = db.get(AccountDeletionRequest, request_id)
    target = db.get(User, deletion.user_id) if deletion else None
    if deletion is None or target is None or not can_manage_account(user, target):
        _deny_target(
            db,
            request,
            user,
            action="admin_cancel_account_deletion",
            target_id=deletion.user_id if deletion else request_id,
        )
    try:
        cancel_account_deletion_by_admin(
            db,
            deletion=deletion,
            target=target,
            reason=payload.reason,
        )
    except AccountDeletionError as exc:
        record_audit(
            db,
            request,
            user,
            "admin_cancel_account_deletion",
            "account_deletion",
            deletion.id,
            target.id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    record_audit(
        db,
        request,
        user,
        "admin_cancel_account_deletion",
        "account_deletion",
        deletion.id,
        target.id,
    )
    db.commit()
    return _deletion_view(deletion, target)


@router.get("/v1/admin/audit", response_model=list[AuditLogView])
def audit_logs(
    request: Request,
    response: Response,
    actor_user_id: str | None = Query(default=None, max_length=36),
    target_user_id: str | None = Query(default=None, max_length=36),
    action: str | None = Query(default=None, max_length=64),
    result: str | None = Query(default=None, pattern=r"^(allowed|denied)$"),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    require_admin(user, request, db, action="list_audit_logs")
    conditions = []
    if user.role == Role.admin:
        ordinary_user_ids = select(User.id).where(User.role == Role.user)
        conditions.append(
            or_(
                AuditLog.actor_user_id == user.id,
                AuditLog.target_user_id.in_(ordinary_user_ids),
            )
        )
    if actor_user_id:
        conditions.append(AuditLog.actor_user_id == actor_user_id)
    if target_user_id:
        conditions.append(AuditLog.target_user_id == target_user_id)
    if action:
        conditions.append(AuditLog.action == action)
    if result:
        conditions.append(AuditLog.result == result)
    if since:
        conditions.append(AuditLog.created_at >= since)
    if until:
        conditions.append(AuditLog.created_at <= until)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.created_at.desc(), AuditLog.id)
        .offset(offset)
        .limit(limit)
    ).all()
    response.headers["X-Total-Count"] = str(total)
    record_audit(db, request, user, "list_audit_logs", "audit_log")
    db.commit()
    return rows
