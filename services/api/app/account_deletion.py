from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path

from sqlalchemy import and_, delete, or_, select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import (
    AccountDeletionRequest,
    AccountDeletionStatus,
    AuditLog,
    JobStatus,
    PageResult,
    PhoneReuseQuarantine,
    ProcessingJob,
    RefreshToken,
    Role,
    ScanPage,
    ScanProject,
    SessionToken,
    SmsChallenge,
    UploadChunk,
    UploadSession,
    User,
    UserIdentity,
    UserStatus,
    VerifiedPhone,
)
from .security import phone_hmac_candidates
from .session_service import revoke_user_sessions
from .sms import consume_sms_challenge


class AccountDeletionError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AccountDeletionRunResult:
    request_id: str
    status: AccountDeletionStatus


def _aware(value: datetime) -> datetime:
    return value if value.tzinfo is not None else value.replace(tzinfo=UTC)


def phone_reuse_blocked(
    db: Session,
    phone: str,
    *,
    now: datetime | None = None,
) -> bool:
    now = now or datetime.now(UTC)
    digests = list(phone_hmac_candidates(phone).values())
    if not digests:
        return False
    return (
        db.scalar(
            select(PhoneReuseQuarantine.id).where(
                PhoneReuseQuarantine.phone_hmac.in_(digests),
                PhoneReuseQuarantine.expires_at > now,
            )
        )
        is not None
    )


def _verify_phone_challenge(
    db: Session,
    *,
    user: User,
    phone: str,
    challenge_id: str,
    code: str,
    purpose: str,
) -> VerifiedPhone:
    verification = consume_sms_challenge(
        db,
        challenge_id=challenge_id,
        phone=phone,
        code=code,
        purpose=purpose,
    )
    if not verification.accepted:
        raise AccountDeletionError(verification.reason, status_code=400)
    digests = list(phone_hmac_candidates(phone).values())
    verified_phone = db.scalar(
        select(VerifiedPhone).where(
            VerifiedPhone.user_id == user.id,
            VerifiedPhone.phone_hmac.in_(digests),
        )
    )
    if verified_phone is None:
        raise AccountDeletionError("account_deletion_phone_mismatch", status_code=400)
    return verified_phone


def request_account_deletion(
    db: Session,
    *,
    actor: User,
    phone: str,
    challenge_id: str,
    code: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AccountDeletionRequest:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    user = db.scalar(select(User).where(User.id == actor.id).with_for_update())
    if user is None or user.status != UserStatus.active:
        raise AccountDeletionError("account_unavailable", status_code=403)
    if user.role == Role.super_admin:
        raise AccountDeletionError("super_admin_protected", status_code=403)
    existing = db.scalar(
        select(AccountDeletionRequest)
        .where(AccountDeletionRequest.user_id == user.id)
        .with_for_update()
    )
    if existing is not None and existing.status != AccountDeletionStatus.canceled:
        raise AccountDeletionError("account_deletion_already_exists")
    _verify_phone_challenge(
        db,
        user=user,
        phone=phone,
        challenge_id=challenge_id,
        code=code,
        purpose="account_deletion",
    )
    if existing is None:
        deletion = AccountDeletionRequest(user_id=user.id)
        db.add(deletion)
    else:
        deletion = existing
    deletion.status = AccountDeletionStatus.pending
    deletion.requested_by_user_id = user.id
    deletion.request_source = "self_service"
    deletion.reason = None
    deletion.cancellation_reason = None
    deletion.requested_at = now
    deletion.execute_after = now + timedelta(days=settings.account_deletion_grace_days)
    deletion.processing_started_at = None
    deletion.canceled_at = None
    deletion.completed_at = None
    deletion.attempts = 0
    deletion.last_error = None
    deletion.resource_counts = None
    user.status = UserStatus.deleting
    revoke_user_sessions(db, user.id)
    db.flush()
    return deletion


def request_admin_account_deletion(
    db: Session,
    *,
    actor: User,
    target: User,
    reason: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AccountDeletionRequest:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    user = db.scalar(select(User).where(User.id == target.id).with_for_update())
    if user is None or user.status not in (UserStatus.active, UserStatus.disabled):
        raise AccountDeletionError("account_unavailable", status_code=409)
    if user.role == Role.super_admin:
        raise AccountDeletionError("super_admin_protected", status_code=403)
    existing = db.scalar(
        select(AccountDeletionRequest)
        .where(AccountDeletionRequest.user_id == user.id)
        .with_for_update()
    )
    if existing is not None and existing.status != AccountDeletionStatus.canceled:
        raise AccountDeletionError("account_deletion_already_exists")
    if existing is None:
        deletion = AccountDeletionRequest(user_id=user.id)
        db.add(deletion)
    else:
        deletion = existing
    deletion.requested_by_user_id = actor.id
    deletion.request_source = "admin"
    deletion.reason = reason
    deletion.cancellation_reason = None
    deletion.status = AccountDeletionStatus.pending
    deletion.requested_at = now
    deletion.execute_after = now + timedelta(days=settings.account_deletion_grace_days)
    deletion.processing_started_at = None
    deletion.canceled_at = None
    deletion.completed_at = None
    deletion.attempts = 0
    deletion.last_error = None
    deletion.resource_counts = None
    user.status = UserStatus.deleting
    revoke_user_sessions(db, user.id)
    db.flush()
    return deletion


def cancel_account_deletion_by_admin(
    db: Session,
    *,
    deletion: AccountDeletionRequest,
    target: User,
    reason: str,
    now: datetime | None = None,
) -> AccountDeletionRequest:
    now = now or datetime.now(UTC)
    if deletion.status != AccountDeletionStatus.pending or target.status != UserStatus.deleting:
        raise AccountDeletionError("account_deletion_not_pending")
    deletion.status = AccountDeletionStatus.canceled
    deletion.canceled_at = now
    deletion.cancellation_reason = reason
    target.status = UserStatus.active
    return deletion


def cancel_account_deletion(
    db: Session,
    *,
    phone: str,
    challenge_id: str,
    code: str,
    now: datetime | None = None,
) -> AccountDeletionRequest:
    now = now or datetime.now(UTC)
    verification = consume_sms_challenge(
        db,
        challenge_id=challenge_id,
        phone=phone,
        code=code,
        purpose="account_deletion_cancel",
    )
    if not verification.accepted:
        raise AccountDeletionError(verification.reason, status_code=400)
    digests = list(phone_hmac_candidates(phone).values())
    verified_phone = db.scalar(
        select(VerifiedPhone).where(VerifiedPhone.phone_hmac.in_(digests)).with_for_update()
    )
    if verified_phone is None:
        raise AccountDeletionError("account_deletion_not_found", status_code=404)
    user = db.scalar(select(User).where(User.id == verified_phone.user_id).with_for_update())
    deletion = db.scalar(
        select(AccountDeletionRequest)
        .where(
            AccountDeletionRequest.user_id == verified_phone.user_id,
            AccountDeletionRequest.status == AccountDeletionStatus.pending,
        )
        .with_for_update()
    )
    if user is None or user.status != UserStatus.deleting or deletion is None:
        raise AccountDeletionError("account_deletion_not_found", status_code=404)
    deletion.status = AccountDeletionStatus.canceled
    deletion.canceled_at = now
    deletion.cancellation_reason = "self_service_sms_verified"
    user.status = UserStatus.active
    return deletion


def _safe_account_path(root: Path, category: str, identifier: str) -> Path:
    if not re.fullmatch(r"[A-Za-z0-9_.:-]{1,100}", identifier):
        raise AccountDeletionError("account_deletion_path_invalid", status_code=500)
    resolved_root = root.resolve()
    candidate = (resolved_root / category / identifier).resolve()
    if resolved_root not in candidate.parents:
        raise AccountDeletionError("account_deletion_path_invalid", status_code=500)
    return candidate


def _quarantine_user_directory(
    deletion: AccountDeletionRequest,
    *,
    settings: Settings,
) -> tuple[Path, Path, bool]:
    source = _safe_account_path(settings.storage_root, "users", deletion.user_id)
    quarantine = _safe_account_path(settings.storage_root, ".account-deletion", deletion.id)
    if source.is_symlink() or quarantine.is_symlink():
        raise AccountDeletionError("account_deletion_path_invalid", status_code=500)
    if source.exists() and quarantine.exists():
        raise AccountDeletionError("account_deletion_path_conflict", status_code=500)
    moved = False
    if source.exists():
        if not source.is_dir():
            raise AccountDeletionError("account_deletion_path_invalid", status_code=500)
        quarantine.parent.mkdir(parents=True, exist_ok=True)
        os.replace(source, quarantine)
        moved = True
    return source, quarantine, moved


def _purge_database_resources(
    db: Session,
    *,
    deletion: AccountDeletionRequest,
    user: User,
    now: datetime,
    settings: Settings,
) -> dict[str, int]:
    phone = db.scalar(
        select(VerifiedPhone).where(VerifiedPhone.user_id == user.id).with_for_update()
    )
    if phone is None:
        raise AccountDeletionError("account_deletion_phone_missing", status_code=500)
    project_ids = list(
        db.scalars(
            select(ScanProject.id).where(ScanProject.owner_user_id == user.id).with_for_update()
        )
    )
    page_ids = list(
        db.scalars(select(ScanPage.id).where(ScanPage.owner_user_id == user.id).with_for_update())
    )
    page_result_ids = list(
        db.scalars(
            select(PageResult.id).where(PageResult.owner_user_id == user.id).with_for_update()
        )
    )
    upload_ids = list(
        db.scalars(
            select(UploadSession.id).where(UploadSession.owner_user_id == user.id).with_for_update()
        )
    )
    session_ids = list(
        db.scalars(select(SessionToken.id).where(SessionToken.user_id == user.id).with_for_update())
    )
    identity_ids = list(
        db.scalars(select(UserIdentity.id).where(UserIdentity.user_id == user.id).with_for_update())
    )
    job_ids = list(
        db.scalars(
            select(ProcessingJob.id).where(ProcessingJob.owner_user_id == user.id).with_for_update()
        )
    )
    chunk_ids = (
        list(
            db.scalars(
                select(UploadChunk.id)
                .where(UploadChunk.upload_id.in_(upload_ids))
                .with_for_update()
            )
        )
        if upload_ids
        else []
    )
    refresh_ids = (
        list(
            db.scalars(
                select(RefreshToken.id)
                .where(RefreshToken.session_id.in_(session_ids))
                .with_for_update()
            )
        )
        if session_ids
        else []
    )
    counts = {
        "identities": len(identity_ids),
        "projects": len(project_ids),
        "pages": len(page_ids),
        "page_results": len(page_result_ids),
        "uploads": len(upload_ids),
        "chunks": len(chunk_ids),
        "jobs": len(job_ids),
        "sessions": len(session_ids),
        "refresh_tokens": len(refresh_ids),
    }
    if chunk_ids:
        db.execute(delete(UploadChunk).where(UploadChunk.id.in_(chunk_ids)))
    if job_ids:
        db.execute(delete(ProcessingJob).where(ProcessingJob.id.in_(job_ids)))
    if upload_ids:
        db.execute(delete(UploadSession).where(UploadSession.id.in_(upload_ids)))
    if page_result_ids:
        db.execute(delete(PageResult).where(PageResult.id.in_(page_result_ids)))
    if page_ids:
        db.execute(delete(ScanPage).where(ScanPage.id.in_(page_ids)))
    if project_ids:
        db.execute(delete(ScanProject).where(ScanProject.id.in_(project_ids)))
    if refresh_ids:
        db.execute(delete(RefreshToken).where(RefreshToken.id.in_(refresh_ids)))
    if session_ids:
        db.execute(delete(SessionToken).where(SessionToken.id.in_(session_ids)))
    if identity_ids:
        db.execute(delete(UserIdentity).where(UserIdentity.id.in_(identity_ids)))
    db.execute(delete(SmsChallenge).where(SmsChallenge.phone_hmac == phone.phone_hmac))
    db.execute(delete(VerifiedPhone).where(VerifiedPhone.id == phone.id))

    quarantine = db.scalar(
        select(PhoneReuseQuarantine).where(PhoneReuseQuarantine.phone_hmac == phone.phone_hmac)
    )
    reuse_after = now + timedelta(days=settings.phone_reuse_quarantine_days)
    if quarantine is None:
        db.add(
            PhoneReuseQuarantine(
                phone_hmac=phone.phone_hmac,
                hmac_key_id=phone.hmac_key_id,
                deletion_request_id=deletion.id,
                expires_at=reuse_after,
                created_at=now,
            )
        )
    elif _aware(quarantine.expires_at) < reuse_after:
        quarantine.expires_at = reuse_after
        quarantine.hmac_key_id = phone.hmac_key_id
        quarantine.deletion_request_id = deletion.id
        quarantine.created_at = now

    user.username = f"deleted-{user.id}"
    user.password_hash = "!deleted"
    user.phone_hmac = hashlib.sha256(f"deleted:{user.id}".encode()).hexdigest()
    user.phone_masked = "已删除"
    user.status = UserStatus.deleted
    user.deleted_at = now
    deletion.status = AccountDeletionStatus.cleanup_pending
    deletion.processing_started_at = deletion.processing_started_at or now
    deletion.attempts += 1
    deletion.last_error = None
    deletion.resource_counts = json.dumps(counts, sort_keys=True, separators=(",", ":"))
    db.add(
        AuditLog(
            actor_user_id=None,
            target_user_id=user.id,
            object_type="account_deletion",
            object_id=deletion.id,
            action="purge_account_data",
            result="allowed",
            created_at=now,
        )
    )
    return counts


def process_account_deletion(
    db: Session,
    request_id: str,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AccountDeletionRunResult:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    deletion = db.scalar(
        select(AccountDeletionRequest)
        .where(AccountDeletionRequest.id == request_id)
        .with_for_update()
    )
    if deletion is None:
        raise AccountDeletionError("account_deletion_not_found", status_code=404)
    if deletion.status in (AccountDeletionStatus.completed, AccountDeletionStatus.canceled):
        return AccountDeletionRunResult(deletion.id, deletion.status)
    if deletion.status == AccountDeletionStatus.pending and _aware(deletion.execute_after) > now:
        return AccountDeletionRunResult(deletion.id, deletion.status)

    source: Path | None = None
    quarantine: Path | None = None
    moved = False
    if deletion.status == AccountDeletionStatus.pending:
        user = db.scalar(select(User).where(User.id == deletion.user_id).with_for_update())
        if user is None or user.status != UserStatus.deleting or user.role == Role.super_admin:
            raise AccountDeletionError("account_deletion_state_invalid", status_code=500)
        running_job = db.scalar(
            select(ProcessingJob.id)
            .where(
                ProcessingJob.owner_user_id == user.id,
                ProcessingJob.status == JobStatus.running,
            )
            .with_for_update()
        )
        if running_job is not None:
            return AccountDeletionRunResult(deletion.id, deletion.status)
        source, quarantine, moved = _quarantine_user_directory(deletion, settings=settings)
        try:
            _purge_database_resources(
                db,
                deletion=deletion,
                user=user,
                now=now,
                settings=settings,
            )
            db.commit()
        except Exception:
            db.rollback()
            if moved and quarantine is not None and source is not None and quarantine.exists():
                source.parent.mkdir(parents=True, exist_ok=True)
                os.replace(quarantine, source)
            raise
    else:
        quarantine = _safe_account_path(settings.storage_root, ".account-deletion", deletion.id)

    try:
        if quarantine.exists():
            if quarantine.is_symlink() or not quarantine.is_dir():
                raise OSError("invalid quarantine path")
            shutil.rmtree(quarantine)
    except FileNotFoundError:
        pass
    except OSError:
        deletion = db.get(AccountDeletionRequest, request_id)
        if deletion is not None and deletion.status == AccountDeletionStatus.cleanup_pending:
            deletion.attempts += 1
            deletion.last_error = "file_cleanup_failed"
            db.commit()
        return AccountDeletionRunResult(request_id, AccountDeletionStatus.cleanup_pending)

    deletion = db.scalar(
        select(AccountDeletionRequest)
        .where(AccountDeletionRequest.id == request_id)
        .with_for_update()
    )
    if deletion is not None and deletion.status == AccountDeletionStatus.cleanup_pending:
        deletion.status = AccountDeletionStatus.completed
        deletion.completed_at = now
        deletion.last_error = None
        db.commit()
    return AccountDeletionRunResult(request_id, AccountDeletionStatus.completed)


def process_next_due_account_deletion(
    db: Session,
    *,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> AccountDeletionRunResult | None:
    now = now or datetime.now(UTC)
    request_id = db.scalar(
        select(AccountDeletionRequest.id)
        .where(
            or_(
                AccountDeletionRequest.status == AccountDeletionStatus.cleanup_pending,
                and_(
                    AccountDeletionRequest.status == AccountDeletionStatus.pending,
                    AccountDeletionRequest.execute_after <= now,
                ),
            )
        )
        .order_by(AccountDeletionRequest.execute_after, AccountDeletionRequest.requested_at)
        .limit(1)
    )
    if request_id is None:
        return None
    return process_account_deletion(db, request_id, now=now, settings=settings)


def main() -> None:
    parser = argparse.ArgumentParser(description="处理已到期的账号删除请求")
    parser.add_argument("--limit", type=int, default=100)
    args = parser.parse_args()
    from .database import SessionLocal
    from .migrations import ensure_database_current

    ensure_database_current()
    processed = 0
    while processed < max(0, args.limit):
        with SessionLocal() as db:
            result = process_next_due_account_deletion(db)
        if result is None:
            break
        processed += 1
        if result.status == AccountDeletionStatus.pending:
            break
    print(f"已处理账号删除请求：{processed}")


if __name__ == "__main__":
    main()
