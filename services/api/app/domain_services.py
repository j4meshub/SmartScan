from __future__ import annotations

import hashlib
import uuid
from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import get_settings
from .identity_services import add_local_identity
from .models import Role, UploadSession, User
from .schemas import TokenResponse, UploadCreate
from .security import hash_password
from .session_service import DeviceMetadata, issue_device_session

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
    password_hash = hash_password(settings.superadmin_password)
    admin = User(
        username="admin",
        password_hash=password_hash,
        phone_hmac=hashlib.sha256(b"superadmin-no-phone").hexdigest(),
        phone_masked="not-bound",
        role=Role.super_admin,
        must_change_password=True,
    )
    db.add(admin)
    db.flush()
    add_local_identity(db, admin, username="admin", credential_hash=password_hash)
    db.commit()


def issue_session(
    db: Session,
    user: User,
    metadata: DeviceMetadata | None = None,
) -> TokenResponse:
    metadata = metadata or DeviceMetadata(
        device_id=f"legacy:{uuid.uuid4()}",
        device_name="旧版客户端",
        platform="legacy",
        legacy=True,
    )
    return issue_device_session(db, user, metadata)


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
