from __future__ import annotations

import re
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from urllib.parse import unquote

from fastapi import Request
from sqlalchemy import exists, or_, select, update
from sqlalchemy.orm import Session

from .models import RefreshToken, SessionToken, User, UserStatus
from .schemas import TokenResponse
from .security import new_refresh_token, new_session, token_hash


class SessionFlowError(RuntimeError):
    def __init__(self, code: str, status_code: int = 401):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class DeviceMetadata:
    device_id: str
    device_name: str
    platform: str
    legacy: bool = False


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def device_metadata_from_request(request: Request) -> DeviceMetadata:
    raw_device_id = request.headers.get("x-device-id", "").strip()
    if not raw_device_id:
        return DeviceMetadata(
            device_id=f"legacy:{uuid.uuid4()}",
            device_name="旧版客户端",
            platform="legacy",
            legacy=True,
        )
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{8,64}", raw_device_id):
        raise SessionFlowError("device_id_invalid", status_code=422)
    device_name = unquote(request.headers.get("x-device-name", "Unnamed device")).strip()
    if not device_name or len(device_name) > 100 or any(ord(char) < 32 for char in device_name):
        raise SessionFlowError("device_name_invalid", status_code=422)
    platform = request.headers.get("x-device-platform", "unknown").strip().lower()
    if not re.fullmatch(r"[a-z0-9_.-]{2,32}", platform):
        raise SessionFlowError("device_platform_invalid", status_code=422)
    return DeviceMetadata(raw_device_id, device_name, platform)


def _revoke_session_ids(db: Session, session_ids: list[str], now: datetime) -> None:
    if not session_ids:
        return
    db.execute(
        update(SessionToken)
        .where(SessionToken.id.in_(session_ids), SessionToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )
    db.execute(
        update(RefreshToken)
        .where(RefreshToken.session_id.in_(session_ids), RefreshToken.revoked_at.is_(None))
        .values(revoked_at=now)
    )


def revoke_user_sessions(
    db: Session,
    user_id: str,
    *,
    except_access_token_hash: str | None = None,
) -> None:
    query = select(SessionToken.id).where(SessionToken.user_id == user_id)
    if except_access_token_hash is not None:
        query = query.where(SessionToken.token_hash != except_access_token_hash)
    session_ids = list(db.scalars(query))
    _revoke_session_ids(db, session_ids, datetime.now(UTC))


def revoke_device_session(db: Session, session: SessionToken) -> None:
    _revoke_session_ids(db, [session.id], datetime.now(UTC))


def issue_device_session(
    db: Session,
    user: User,
    metadata: DeviceMetadata,
) -> TokenResponse:
    now = datetime.now(UTC)
    existing_ids = list(
        db.scalars(
            select(SessionToken.id).where(
                SessionToken.user_id == user.id,
                SessionToken.device_id == metadata.device_id,
                SessionToken.revoked_at.is_(None),
            )
        )
    )
    _revoke_session_ids(db, existing_ids, now)
    access_raw, access_digest, access_expires = new_session(legacy=metadata.legacy)
    refresh_raw, refresh_digest, refresh_expires = new_refresh_token()
    device_session = SessionToken(
        user_id=user.id,
        token_hash=access_digest,
        device_id=metadata.device_id,
        device_name=metadata.device_name,
        platform=metadata.platform,
        expires_at=access_expires,
        last_seen_at=now,
        created_at=now,
    )
    db.add(device_session)
    db.flush()
    db.add(
        RefreshToken(
            session_id=device_session.id,
            token_hash=refresh_digest,
            expires_at=refresh_expires,
            created_at=now,
        )
    )
    db.commit()
    return TokenResponse(
        access_token=access_raw,
        expires_at=access_expires,
        refresh_token=refresh_raw,
        refresh_expires_at=refresh_expires,
        session_id=device_session.id,
        device_id=device_session.device_id,
    )


def rotate_refresh_token(db: Session, raw_refresh_token: str) -> TokenResponse:
    digest = token_hash(raw_refresh_token)
    refresh = db.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == digest).with_for_update()
    )
    if refresh is None:
        raise SessionFlowError("refresh_token_invalid")
    device_session = db.scalar(
        select(SessionToken).where(SessionToken.id == refresh.session_id).with_for_update()
    )
    now = datetime.now(UTC)
    if refresh.consumed_at is not None:
        if device_session is not None:
            revoke_device_session(db, device_session)
        db.commit()
        raise SessionFlowError("refresh_token_replayed")
    if (
        device_session is None
        or device_session.revoked_at is not None
        or refresh.revoked_at is not None
        or _aware(refresh.expires_at) <= now
    ):
        if device_session is not None:
            revoke_device_session(db, device_session)
        db.commit()
        raise SessionFlowError("refresh_token_invalid")
    user = db.get(User, device_session.user_id)
    if user is None or user.status != UserStatus.active:
        revoke_device_session(db, device_session)
        db.commit()
        raise SessionFlowError("account_unavailable")

    access_raw, access_digest, access_expires = new_session()
    next_raw, next_digest, next_expires = new_refresh_token()
    next_refresh = RefreshToken(
        session_id=device_session.id,
        token_hash=next_digest,
        expires_at=next_expires,
        created_at=now,
    )
    db.add(next_refresh)
    db.flush()
    refresh.consumed_at = now
    refresh.replaced_by_id = next_refresh.id
    device_session.token_hash = access_digest
    device_session.expires_at = access_expires
    device_session.last_seen_at = now
    db.commit()
    return TokenResponse(
        access_token=access_raw,
        expires_at=access_expires,
        refresh_token=next_raw,
        refresh_expires_at=next_expires,
        session_id=device_session.id,
        device_id=device_session.device_id,
    )


def access_session(db: Session, authorization: str, *, lock: bool = False) -> SessionToken:
    if not authorization.lower().startswith("bearer "):
        raise SessionFlowError("invalid_session")
    query = select(SessionToken).where(
        SessionToken.token_hash == token_hash(authorization.split(" ", 1)[1])
    )
    if lock:
        query = query.with_for_update()
    session = db.scalar(query)
    if session is None:
        raise SessionFlowError("invalid_session")
    return session


def active_device_sessions(db: Session, user_id: str) -> list[SessionToken]:
    now = datetime.now(UTC)
    has_active_refresh = exists(
        select(RefreshToken.id).where(
            RefreshToken.session_id == SessionToken.id,
            RefreshToken.consumed_at.is_(None),
            RefreshToken.revoked_at.is_(None),
            RefreshToken.expires_at > now,
        )
    )
    return list(
        db.scalars(
            select(SessionToken)
            .where(
                SessionToken.user_id == user_id,
                SessionToken.revoked_at.is_(None),
                or_(SessionToken.expires_at > now, has_active_refresh),
            )
            .order_by(SessionToken.last_seen_at.desc())
        )
    )
