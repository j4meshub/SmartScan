from __future__ import annotations

from datetime import UTC, datetime

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .database import get_db
from .models import SessionToken, User, UserStatus
from .security import token_hash


def current_user(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> User:
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="authentication required"
        )
    digest = token_hash(authorization.split(" ", 1)[1])
    session = db.scalar(select(SessionToken).where(SessionToken.token_hash == digest))
    now = datetime.now(UTC)
    if not session or session.revoked_at or session.expires_at.replace(tzinfo=UTC) <= now:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="invalid session")
    user = db.get(User, session.user_id)
    if not user or user.status != UserStatus.active:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="account unavailable")
    return user
