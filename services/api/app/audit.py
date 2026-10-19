from __future__ import annotations

from fastapi import Request
from sqlalchemy.orm import Session

from .models import AuditLog, User


def record_audit(
    db: Session,
    request: Request,
    actor: User | None,
    action: str,
    object_type: str,
    object_id: str | None = None,
    target_user_id: str | None = None,
    result: str = "allowed",
) -> None:
    forwarded = request.headers.get("x-forwarded-for", "")
    ip = forwarded.split(",")[0].strip() or (request.client.host if request.client else None)
    db.add(
        AuditLog(
            actor_user_id=actor.id if actor else None,
            target_user_id=target_user_id,
            object_type=object_type,
            object_id=object_id,
            action=action,
            result=result,
            request_id=getattr(request.state, "request_id", None),
            ip=ip,
            user_agent=request.headers.get("user-agent", "")[:255],
        )
    )
