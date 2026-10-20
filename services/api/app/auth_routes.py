from __future__ import annotations

from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .audit import record_audit
from .config import get_settings
from .database import get_db
from .dependencies import current_user
from .domain_services import issue_session
from .identity_services import (
    add_local_identity,
    add_verified_phone,
    local_identity_by_username,
    local_identity_for_user,
    user_view,
    verified_phone_by_hmac,
)
from .models import SessionToken, User, UserStatus
from .schemas import LoginRequest, PasswordChange, RegisterRequest, TokenResponse, UserView
from .security import hash_password, mask_phone, phone_hmac, token_hash, verify_password

settings = get_settings()
router = APIRouter()


@router.post("/v1/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    if settings.env != "development" or payload.sms_code != settings.dev_sms_code:
        raise HTTPException(status_code=400, detail="invalid verification code")
    digest = phone_hmac(payload.phone)
    existing_phone = verified_phone_by_hmac(db, digest)
    existing_identity = local_identity_by_username(db, payload.username)
    if existing_identity:
        raise HTTPException(status_code=409, detail="username already exists")
    if existing_phone:
        phone_owner = db.get(User, existing_phone.user_id)
        if not phone_owner or phone_owner.status != UserStatus.active:
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
    add_local_identity(
        db,
        user,
        username=payload.username,
        credential_hash=password_hash,
    )
    add_verified_phone(
        db,
        user,
        phone_hmac=digest,
        phone_masked=user.phone_masked,
        verification_source="development_sms",
    )
    record_audit(db, request, user, "register", "user", user.id, user.id)
    return issue_session(db, user)


@router.post("/v1/auth/login", response_model=TokenResponse)
def login(payload: LoginRequest, request: Request, db: Session = Depends(get_db)):
    identity = local_identity_by_username(db, payload.username)
    user = db.get(User, identity.user_id) if identity else None
    credential_hash = identity.credential_hash if identity else None
    if not user or not credential_hash or not verify_password(payload.password, credential_hash):
        record_audit(db, request, None, "login", "user", result="denied")
        db.commit()
        raise HTTPException(status_code=401, detail="invalid credentials")
    if user.status != UserStatus.active:
        raise HTTPException(status_code=403, detail="account unavailable")
    identity.last_login_at = datetime.now(UTC)
    record_audit(db, request, user, "login", "user", user.id, user.id)
    return issue_session(db, user)


@router.post("/v1/auth/logout", status_code=204)
def logout(
    authorization: str = Header(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    digest = token_hash(authorization.split(" ", 1)[1])
    token = db.scalar(select(SessionToken).where(SessionToken.token_hash == digest))
    if token:
        token.revoked_at = datetime.now(UTC)
        db.commit()


@router.get("/v1/me", response_model=UserView)
def me(user: User = Depends(current_user), db: Session = Depends(get_db)):
    return user_view(db, user)


@router.post("/v1/me/password", status_code=204)
def change_password(
    payload: PasswordChange,
    request: Request,
    authorization: str = Header(...),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    identity = local_identity_for_user(db, user.id)
    credential_hash = identity.credential_hash if identity else None
    if not credential_hash or not verify_password(payload.current_password, credential_hash):
        raise HTTPException(status_code=400, detail="current password is incorrect")
    try:
        new_hash = hash_password(payload.new_password)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc
    assert identity is not None
    identity.credential_hash = new_hash
    user.password_hash = new_hash
    user.must_change_password = False
    current_digest = token_hash(authorization.split(" ", 1)[1])
    db.execute(
        update(SessionToken)
        .where(SessionToken.user_id == user.id, SessionToken.token_hash != current_digest)
        .values(revoked_at=datetime.now(UTC))
    )
    record_audit(db, request, user, "change_password", "user", user.id, user.id)
    db.commit()
