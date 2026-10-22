from __future__ import annotations

import hashlib
import secrets
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import select, update
from sqlalchemy.orm import Session

from .ai_business import AI_CONSENT_VERSION
from .config import Settings, get_settings
from .models import (
    AiEnhancementTask,
    AiMediaGrant,
    PageResult,
    ScanPage,
    ScanProject,
)

SUPPORTED_MEDIA_TYPES = {"image/jpeg", "image/png", "image/webp"}


class AiMediaError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class IssuedMediaGrant:
    grant: AiMediaGrant
    access_token: str


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def _token_hash(token: str) -> str:
    return hashlib.sha256(token.encode("ascii")).hexdigest()


def _safe_result_path(settings: Settings, result: PageResult) -> Path:
    root = settings.storage_root.resolve()
    absolute = (root / result.file_path).resolve()
    if root not in absolute.parents or not absolute.is_file():
        raise AiMediaError("ai_media_source_unavailable", status_code=404)
    return absolute


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for chunk in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def issue_media_grant(
    db: Session,
    *,
    enhancement_task_id: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> IssuedMediaGrant:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    task = db.scalar(
        select(AiEnhancementTask)
        .where(AiEnhancementTask.id == enhancement_task_id)
        .with_for_update()
    )
    if task is None or task.status not in {"queued", "processing"}:
        raise AiMediaError("ai_enhancement_not_dispatchable", status_code=404)
    project = db.get(ScanProject, task.project_id)
    page = db.get(ScanPage, task.page_id)
    if (
        project is None
        or page is None
        or project.owner_user_id != task.owner_user_id
        or page.owner_user_id != task.owner_user_id
        or not project.ai_enabled
        or project.ai_consent_version != AI_CONSENT_VERSION
    ):
        raise AiMediaError("project_ai_not_enabled")
    if page.active_result_version != task.source_result_version:
        task.status = "stale"
        task.updated_at = now
        raise AiMediaError("ai_source_version_conflict")
    result = db.scalar(
        select(PageResult).where(
            PageResult.page_id == page.id,
            PageResult.version == task.source_result_version,
        )
    )
    if result is None or result.owner_user_id != task.owner_user_id:
        raise AiMediaError("ai_media_source_unavailable", status_code=404)
    if result.mime_type not in SUPPORTED_MEDIA_TYPES:
        raise AiMediaError("ai_media_type_not_supported", status_code=422)
    absolute = _safe_result_path(settings, result)
    size_bytes = absolute.stat().st_size
    sha256 = _file_sha256(absolute)
    if result.size_bytes is not None and result.size_bytes != size_bytes:
        raise AiMediaError("ai_media_source_changed", status_code=409)
    if result.sha256 is not None and not secrets.compare_digest(result.sha256, sha256):
        raise AiMediaError("ai_media_source_changed", status_code=409)

    db.execute(
        update(AiMediaGrant)
        .where(
            AiMediaGrant.enhancement_task_id == task.id,
            AiMediaGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now)
    )
    access_token = secrets.token_urlsafe(32)
    grant = AiMediaGrant(
        enhancement_task_id=task.id,
        owner_user_id=task.owner_user_id,
        project_id=task.project_id,
        page_id=task.page_id,
        page_result_id=result.id,
        source_result_version=task.source_result_version,
        token_hash=_token_hash(access_token),
        mime_type=result.mime_type,
        sha256=sha256,
        byte_size=size_bytes,
        expires_at=now + timedelta(seconds=settings.ai_media_grant_ttl_seconds),
        access_count=0,
        created_at=now,
    )
    db.add(grant)
    db.flush()
    return IssuedMediaGrant(grant=grant, access_token=access_token)


def resolve_media_grant(
    db: Session,
    *,
    access_token: str,
    settings: Settings | None = None,
    now: datetime | None = None,
) -> tuple[AiMediaGrant, Path] | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    if len(access_token) < 22 or len(access_token) > 128:
        return None
    try:
        token_hash = _token_hash(access_token)
    except UnicodeEncodeError:
        return None
    grant = db.scalar(
        select(AiMediaGrant).where(AiMediaGrant.token_hash == token_hash).with_for_update()
    )
    if grant is None or not secrets.compare_digest(grant.token_hash, token_hash):
        return None
    if grant.revoked_at is not None or _aware(grant.expires_at) <= now:
        return None
    task = db.get(AiEnhancementTask, grant.enhancement_task_id)
    project = db.get(ScanProject, grant.project_id)
    page = db.get(ScanPage, grant.page_id)
    result = db.get(PageResult, grant.page_result_id)
    if (
        task is None
        or project is None
        or page is None
        or result is None
        or task.status not in {"queued", "processing"}
        or not project.ai_enabled
        or project.ai_consent_version != AI_CONSENT_VERSION
        or page.active_result_version != grant.source_result_version
        or result.version != grant.source_result_version
        or result.page_id != grant.page_id
    ):
        grant.revoked_at = now
        return None
    try:
        absolute = _safe_result_path(settings, result)
    except AiMediaError:
        grant.revoked_at = now
        return None
    stat = absolute.stat()
    if stat.st_size != grant.byte_size or _file_sha256(absolute) != grant.sha256:
        grant.revoked_at = now
        return None
    grant.last_accessed_at = now
    grant.access_count += 1
    return grant, absolute


def revoke_task_media_grants(
    db: Session, enhancement_task_id: str, *, now: datetime | None = None
) -> None:
    db.execute(
        update(AiMediaGrant)
        .where(
            AiMediaGrant.enhancement_task_id == enhancement_task_id,
            AiMediaGrant.revoked_at.is_(None),
        )
        .values(revoked_at=now or datetime.now(UTC))
    )
