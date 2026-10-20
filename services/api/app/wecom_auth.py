from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from urllib.parse import urlencode

from sqlalchemy import select
from sqlalchemy.orm import Session

from .account_deletion import phone_reuse_blocked
from .config import Settings, get_settings
from .identity_services import add_verified_phone
from .models import (
    User,
    UserIdentity,
    UserStatus,
    VerifiedPhone,
    WeComBindingTicket,
    WeComOAuthState,
)
from .phone_protection import protect_phone
from .security import hash_password, mask_phone, phone_hmac, phone_hmac_candidates
from .wecom import WeComAccountDecision, WeComIdentity, decide_wecom_account_action

WECOM_AUTHORIZE_URL = "https://open.weixin.qq.com/connect/oauth2/authorize"


class WeComAuthError(RuntimeError):
    pass


@dataclass(frozen=True)
class OAuthStart:
    authorization_url: str
    expires_at: datetime
    state: str


@dataclass(frozen=True)
class OAuthOutcome:
    decision: WeComAccountDecision
    user: User | None = None
    binding_ticket: str | None = None
    binding_expires_at: datetime | None = None


def _digest(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def create_oauth_start(
    db: Session,
    *,
    settings: Settings | None = None,
) -> OAuthStart:
    settings = settings or get_settings()
    if settings.wecom_mode == "disabled":
        raise WeComAuthError("wecom_disabled")
    if not settings.wecom_corp_id or not settings.wecom_agent_id or not settings.wecom_redirect_uri:
        raise WeComAuthError("wecom_oauth_configuration_incomplete")
    raw_state = secrets.token_urlsafe(32)
    now = datetime.now(UTC)
    expires = now + timedelta(seconds=settings.wecom_state_ttl_seconds)
    db.add(
        WeComOAuthState(
            state_hash=_digest(raw_state),
            expires_at=expires,
            created_at=now,
        )
    )
    query = urlencode(
        {
            "appid": settings.wecom_corp_id,
            "agentid": settings.wecom_agent_id,
            "redirect_uri": settings.wecom_redirect_uri,
            "response_type": "code",
            "scope": "snsapi_base",
            "state": raw_state,
        }
    )
    return OAuthStart(f"{WECOM_AUTHORIZE_URL}?{query}#wechat_redirect", expires, raw_state)


def consume_oauth_state(db: Session, raw_state: str) -> WeComOAuthState:
    state = db.scalar(
        select(WeComOAuthState)
        .where(WeComOAuthState.state_hash == _digest(raw_state))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if state is None:
        raise WeComAuthError("wecom_state_invalid")
    if state.consumed_at is not None:
        raise WeComAuthError("wecom_state_consumed")
    if _aware(state.expires_at) <= now:
        raise WeComAuthError("wecom_state_expired")
    state.consumed_at = now
    return state


def _phone_user_ids(db: Session, phone: str) -> list[str]:
    digests = list(phone_hmac_candidates(phone).values())
    return list(
        db.scalars(select(VerifiedPhone.user_id).where(VerifiedPhone.phone_hmac.in_(digests)))
    )


def _create_wecom_user(db: Session, identity: WeComIdentity) -> User:
    if identity.phone_e164 is None:
        raise WeComAuthError("wecom_phone_required")
    if phone_reuse_blocked(db, identity.phone_e164):
        raise WeComAuthError("wecom_phone_temporarily_unavailable")
    user_id = str(uuid.uuid4())
    digest = phone_hmac(identity.phone_e164)
    user = User(
        id=user_id,
        username=f"wecom_{hashlib.sha256(identity.provider_subject.encode()).hexdigest()[:24]}",
        password_hash=hash_password(secrets.token_urlsafe(48)),
        phone_hmac=digest,
        phone_masked=mask_phone(identity.phone_e164),
    )
    db.add(user)
    db.flush()
    db.add(
        UserIdentity(
            user_id=user.id,
            provider="wecom",
            provider_subject=identity.provider_subject,
        )
    )
    add_verified_phone(
        db,
        user,
        protected=protect_phone(identity.phone_e164, user_id=user.id),
        verification_source=identity.assurance,
    )
    return user


def resolve_wecom_identity(db: Session, identity: WeComIdentity) -> OAuthOutcome:
    bound = db.scalar(
        select(UserIdentity).where(
            UserIdentity.provider == "wecom",
            UserIdentity.provider_subject == identity.provider_subject,
        )
    )
    candidates = _phone_user_ids(db, identity.phone_e164) if identity.phone_e164 else []
    decision = decide_wecom_account_action(
        identity,
        bound_identity_user_id=bound.user_id if bound else None,
        phone_candidate_user_ids=candidates,
    )
    if decision.action == "use_bound_identity":
        user = db.get(User, decision.canonical_user_id)
        if user is None or user.status != UserStatus.active:
            raise WeComAuthError("wecom_account_unavailable")
        if bound is not None:
            bound.last_login_at = datetime.now(UTC)
        return OAuthOutcome(decision, user=user)
    if decision.action == "bind_verified_phone":
        user = db.get(User, decision.canonical_user_id)
        if user is None or user.status != UserStatus.active:
            raise WeComAuthError("wecom_account_unavailable")
        existing_for_user = db.scalar(
            select(UserIdentity).where(
                UserIdentity.user_id == user.id,
                UserIdentity.provider == "wecom",
            )
        )
        if existing_for_user is not None:
            return OAuthOutcome(WeComAccountDecision("require_conflict_review"))
        db.add(
            UserIdentity(
                user_id=user.id,
                provider="wecom",
                provider_subject=identity.provider_subject,
            )
        )
        return OAuthOutcome(decision, user=user)
    if decision.action == "create_wecom_user":
        return OAuthOutcome(decision, user=_create_wecom_user(db, identity))
    if decision.action == "require_phone_binding":
        raw_ticket = secrets.token_urlsafe(32)
        expires = datetime.now(UTC) + timedelta(seconds=get_settings().wecom_binding_ttl_seconds)
        db.add(
            WeComBindingTicket(
                ticket_hash=_digest(raw_ticket),
                provider_subject=identity.provider_subject,
                assurance=identity.assurance,
                expires_at=expires,
            )
        )
        return OAuthOutcome(
            decision,
            binding_ticket=raw_ticket,
            binding_expires_at=expires,
        )
    return OAuthOutcome(decision)


def consume_binding_ticket(db: Session, raw_ticket: str) -> WeComBindingTicket:
    ticket = db.scalar(
        select(WeComBindingTicket)
        .where(WeComBindingTicket.ticket_hash == _digest(raw_ticket))
        .with_for_update()
    )
    now = datetime.now(UTC)
    if ticket is None:
        raise WeComAuthError("wecom_binding_ticket_invalid")
    if ticket.consumed_at is not None:
        raise WeComAuthError("wecom_binding_ticket_consumed")
    if _aware(ticket.expires_at) <= now:
        raise WeComAuthError("wecom_binding_ticket_expired")
    return ticket
