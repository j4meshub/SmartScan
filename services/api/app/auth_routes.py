from __future__ import annotations

import hmac
from datetime import UTC, datetime

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, Response
from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .account_merge import AccountMergeError, merge_accounts
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
    verified_phone_by_hmacs,
)
from .models import SessionToken, User, UserStatus
from .phone_protection import protect_phone
from .schemas import (
    AccountMergeRequest,
    AccountMergeView,
    LoginRequest,
    PasswordChange,
    RegisterRequest,
    SmsChallengeRequest,
    SmsChallengeView,
    TokenResponse,
    UserView,
    WeComAuthorizeView,
    WeComCallbackView,
    WeComPhoneBindRequest,
)
from .security import (
    hash_password,
    mask_phone,
    phone_hmac,
    phone_hmac_candidates,
    token_hash,
    verify_password,
)
from .sms import (
    SmsProviderError,
    SmsRateLimitError,
    consume_sms_challenge,
    create_sms_challenge,
    create_sms_provider,
)
from .wecom import WeComAdapterError, WeComIdentity, create_wecom_adapter
from .wecom_auth import (
    WeComAuthError,
    consume_binding_ticket,
    consume_oauth_state,
    create_oauth_start,
    resolve_wecom_identity,
)

settings = get_settings()
router = APIRouter()
WECOM_OAUTH_COOKIE = "smartscan_wecom_oauth_state"


@router.post("/v1/auth/account-merges", response_model=AccountMergeView)
def account_merge(
    payload: AccountMergeRequest,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    try:
        outcome = merge_accounts(
            db,
            actor=user,
            phone=payload.phone,
            sms_challenge_id=payload.sms_challenge_id,
            sms_code=payload.sms_code,
            idempotency_key=payload.idempotency_key,
        )
    except AccountMergeError as exc:
        record_audit(db, request, user, "merge_account", "account_merge", result="denied")
        db.commit()
        raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc
    record_audit(
        db,
        request,
        user,
        "merge_account",
        "account_merge",
        outcome.audit.id,
        outcome.audit.canonical_user_id,
    )
    db.commit()
    return AccountMergeView(
        merge_id=outcome.audit.id,
        canonical_user_id=outcome.audit.canonical_user_id,
        source_user_id=outcome.audit.source_user_id,
        result=outcome.audit.result,
        merged_at=outcome.audit.created_at,
    )


@router.post("/v1/auth/wecom/authorize", response_model=WeComAuthorizeView, status_code=201)
def wecom_authorize(response: Response, db: Session = Depends(get_db)):
    try:
        start = create_oauth_start(db)
    except WeComAuthError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    db.commit()
    response.set_cookie(
        WECOM_OAUTH_COOKIE,
        start.state,
        max_age=settings.wecom_state_ttl_seconds,
        path="/v1/auth/wecom/callback",
        secure=settings.env != "development",
        httponly=True,
        samesite="lax",
    )
    return WeComAuthorizeView(
        authorization_url=start.authorization_url,
        expires_at=start.expires_at,
    )


@router.get("/v1/auth/wecom/callback", response_model=WeComCallbackView)
def wecom_callback(
    request: Request,
    code: str = Query(min_length=1, max_length=512),
    state: str = Query(min_length=20, max_length=256),
    db: Session = Depends(get_db),
):
    try:
        intent_state = request.cookies.get(WECOM_OAUTH_COOKIE)
        if intent_state is None or not hmac.compare_digest(intent_state, state):
            raise WeComAuthError("wecom_intent_invalid")
        consume_oauth_state(db, state)
        db.commit()
        identity = create_wecom_adapter(settings).resolve(code)
        outcome = resolve_wecom_identity(db, identity)
    except (WeComAuthError, WeComAdapterError) as exc:
        record_audit(db, request, None, "wecom_callback", "wecom_identity", result="denied")
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if outcome.user is not None:
        record_audit(
            db,
            request,
            outcome.user,
            "wecom_login",
            "user",
            outcome.user.id,
            outcome.user.id,
        )
        token = issue_session(db, outcome.user)
        return WeComCallbackView(
            action=outcome.decision.action,
            access_token=token.access_token,
            expires_at=token.expires_at,
        )
    db.commit()
    if outcome.decision.action == "require_conflict_review":
        record_audit(
            db,
            request,
            None,
            "wecom_identity_conflict",
            "wecom_identity",
            result="denied",
        )
        db.commit()
        raise HTTPException(status_code=409, detail="wecom_identity_conflict")
    return WeComCallbackView(
        action=outcome.decision.action,
        binding_ticket=outcome.binding_ticket,
        binding_expires_at=outcome.binding_expires_at,
    )


@router.post("/v1/auth/wecom/bind-phone", response_model=TokenResponse)
def wecom_bind_phone(
    payload: WeComPhoneBindRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    try:
        ticket = consume_binding_ticket(db, payload.binding_ticket)
    except WeComAuthError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    verification = consume_sms_challenge(
        db,
        challenge_id=payload.sms_challenge_id,
        phone=payload.phone,
        code=payload.sms_code,
        purpose="wecom_binding",
    )
    if not verification.accepted:
        db.commit()
        raise HTTPException(status_code=400, detail=verification.reason)
    corp_id, separator, user_id = ticket.provider_subject.partition(":")
    if not separator or not corp_id or not user_id:
        db.commit()
        raise HTTPException(status_code=400, detail="wecom_binding_ticket_invalid")
    identity = WeComIdentity(
        corp_id=corp_id,
        user_id=user_id,
        phone_e164=payload.phone,
        assurance=ticket.assurance,
    )
    try:
        outcome = resolve_wecom_identity(db, identity)
    except WeComAuthError as exc:
        db.commit()
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if outcome.user is None:
        db.commit()
        raise HTTPException(status_code=409, detail="wecom_identity_conflict")
    ticket.consumed_at = datetime.now(UTC)
    record_audit(
        db,
        request,
        outcome.user,
        "bind_wecom_identity",
        "user",
        outcome.user.id,
        outcome.user.id,
    )
    return issue_session(db, outcome.user)


@router.post(
    "/v1/auth/sms/challenges",
    response_model=SmsChallengeView,
    status_code=201,
)
def request_sms_challenge(
    payload: SmsChallengeRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    requester_ip = request.client.host if request.client else "unknown"
    try:
        challenge = create_sms_challenge(
            db,
            phone=payload.phone,
            purpose=payload.purpose,
            requester_ip=requester_ip,
            provider=create_sms_provider(),
        )
    except SmsRateLimitError as exc:
        db.rollback()
        raise HTTPException(
            status_code=429,
            detail=str(exc),
            headers={"Retry-After": str(settings.sms_rate_window_seconds)},
        ) from exc
    except SmsProviderError as exc:
        db.rollback()
        raise HTTPException(status_code=503, detail=str(exc)) from exc
    record_audit(
        db,
        request,
        None,
        "request_sms_challenge",
        "sms_challenge",
        challenge.id,
    )
    db.commit()
    return SmsChallengeView(
        challenge_id=challenge.id,
        expires_at=challenge.expires_at,
        retry_after_seconds=settings.sms_rate_window_seconds,
    )


@router.post("/v1/auth/register", response_model=TokenResponse, status_code=201)
def register(payload: RegisterRequest, request: Request, db: Session = Depends(get_db)):
    candidates = phone_hmac_candidates(payload.phone)
    digest = phone_hmac(payload.phone)
    existing_phone = verified_phone_by_hmacs(db, list(candidates.values()))
    existing_identity = local_identity_by_username(db, payload.username)
    if existing_identity:
        raise HTTPException(status_code=409, detail="username already exists")
    if existing_phone:
        phone_owner = db.get(User, existing_phone.user_id)
        if not phone_owner or phone_owner.status != UserStatus.active:
            raise HTTPException(status_code=403, detail="phone is linked to an unavailable account")
        raise HTTPException(status_code=409, detail="phone already registered; use account binding")
    verification_source = "development_sms"
    if payload.sms_challenge_id:
        verification = consume_sms_challenge(
            db,
            challenge_id=payload.sms_challenge_id,
            phone=payload.phone,
            code=payload.sms_code,
            purpose="registration",
        )
        if not verification.accepted:
            record_audit(
                db,
                request,
                None,
                "verify_sms_challenge",
                "sms_challenge",
                payload.sms_challenge_id,
                result="denied",
            )
            db.commit()
            raise HTTPException(status_code=400, detail=verification.reason)
        verification_source = verification.verification_source or "sms"
    elif settings.env != "development" or payload.sms_code != settings.dev_sms_code:
        raise HTTPException(status_code=400, detail="invalid verification code")
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
    protected = protect_phone(payload.phone, user_id=user.id)
    add_local_identity(
        db,
        user,
        username=payload.username,
        credential_hash=password_hash,
    )
    add_verified_phone(
        db,
        user,
        protected=protected,
        verification_source=verification_source,
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
