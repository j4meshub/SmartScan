from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, or_, select, text, update
from sqlalchemy.orm import Session, aliased

from .config import Settings, get_settings
from .models import AiEnhancementTask, AiMediaGrant, JobStatus, ProcessingJob, User


class JobFlowError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class JobClaim:
    job_id: str
    lease_token: str
    worker_id: str


def job_for_owner(db: Session, actor: User, job_id: str, *, lock: bool = False) -> ProcessingJob:
    statement = select(ProcessingJob).where(
        ProcessingJob.id == job_id,
        ProcessingJob.owner_user_id == actor.id,
    )
    if lock:
        statement = statement.with_for_update()
    job = db.scalar(statement)
    if job is None:
        raise JobFlowError("job_not_found", status_code=404)
    return job


def _clear_lease(job: ProcessingJob) -> None:
    job.lease_owner = None
    job.lease_token = None
    job.lease_until = None
    job.heartbeat_at = None


def _finalize_exhausted_leases(db: Session, now: datetime) -> None:
    exhausted = db.scalars(
        select(ProcessingJob)
        .where(
            ProcessingJob.status.in_([JobStatus.baseline_processing, JobStatus.optional_enhancing]),
            ProcessingJob.lease_until < now,
            ProcessingJob.attempts >= ProcessingJob.max_attempts,
        )
        .with_for_update(skip_locked=True)
    ).all()
    for job in exhausted:
        job.status = JobStatus.failed_final
        job.error_code = job.error_code or "lease_expired"
        job.error = job.error or "worker lease expired after maximum attempts"
        job.completed_at = now
        _clear_lease(job)
        if job.kind == "ai_enhancement":
            task = db.scalar(
                select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id)
            )
            if task is not None:
                task.status = "failed"
                task.error_code = job.error_code
                task.updated_at = now
                db.execute(
                    update(AiMediaGrant)
                    .where(
                        AiMediaGrant.enhancement_task_id == task.id,
                        AiMediaGrant.revoked_at.is_(None),
                    )
                    .values(revoked_at=now)
                )


def _claim_job_row(
    job: ProcessingJob,
    *,
    worker_id: str,
    now: datetime,
    settings: Settings,
    processing_status: JobStatus = JobStatus.baseline_processing,
) -> JobClaim:
    token = str(uuid.uuid4())
    job.status = processing_status
    job.attempts += 1
    job.progress = max(job.progress, 5)
    job.started_at = job.started_at or now
    job.lease_owner = worker_id
    job.lease_token = token
    job.lease_until = now + timedelta(seconds=settings.job_lease_seconds)
    job.heartbeat_at = now
    job.error_code = None
    job.error = None
    return JobClaim(job.id, token, worker_id)


def _lock_job_owner(db: Session, owner_user_id: str) -> None:
    if db.get_bind().dialect.name == "postgresql":
        db.execute(
            text("SELECT pg_advisory_xact_lock(hashtextextended(:owner_user_id, 1))"),
            {"owner_user_id": owner_user_id},
        )


def _active_owner_jobs(db: Session, owner_user_id: str, now: datetime) -> int:
    return int(
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.owner_user_id == owner_user_id,
                ProcessingJob.status.in_(
                    [JobStatus.baseline_processing, JobStatus.optional_enhancing]
                ),
                ProcessingJob.lease_until >= now,
            )
        )
        or 0
    )


def claim_next_job(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> JobClaim | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    _finalize_exhausted_leases(db, now)
    claimable_status = or_(
        ProcessingJob.status == JobStatus.queued,
        ProcessingJob.status == JobStatus.failed_retryable,
        (
            (ProcessingJob.status == JobStatus.baseline_processing)
            & (ProcessingJob.lease_until < now)
        ),
    )
    active = aliased(ProcessingJob)
    active_owner_count = (
        select(func.count())
        .select_from(active)
        .where(
            active.owner_user_id == ProcessingJob.owner_user_id,
            active.status.in_([JobStatus.baseline_processing, JobStatus.optional_enhancing]),
            active.lease_until >= now,
        )
        .correlate(ProcessingJob)
        .scalar_subquery()
    )
    job = db.scalar(
        select(ProcessingJob)
        .where(
            claimable_status,
            ProcessingJob.kind != "ai_enhancement",
            ProcessingJob.available_at <= now,
            ProcessingJob.attempts < ProcessingJob.max_attempts,
            active_owner_count < settings.max_active_jobs_per_user,
        )
        .order_by(
            ProcessingJob.priority.desc(),
            ProcessingJob.created_at,
            ProcessingJob.id,
        )
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    _lock_job_owner(db, job.owner_user_id)
    if _active_owner_jobs(db, job.owner_user_id, now) >= settings.max_active_jobs_per_user:
        return None
    claim = _claim_job_row(job, worker_id=worker_id, now=now, settings=settings)
    db.flush()
    return claim


def claim_next_ai_job(
    db: Session,
    *,
    worker_id: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> JobClaim | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    _finalize_exhausted_leases(db, now)
    claimable_status = or_(
        ProcessingJob.status == JobStatus.queued,
        ProcessingJob.status == JobStatus.failed_retryable,
        (
            (ProcessingJob.status == JobStatus.optional_enhancing)
            & (ProcessingJob.lease_until < now)
        ),
    )
    job = db.scalar(
        select(ProcessingJob)
        .where(
            claimable_status,
            ProcessingJob.kind == "ai_enhancement",
            ProcessingJob.available_at <= now,
            ProcessingJob.attempts < ProcessingJob.max_attempts,
        )
        .order_by(ProcessingJob.priority.desc(), ProcessingJob.created_at, ProcessingJob.id)
        .with_for_update(skip_locked=True)
        .limit(1)
    )
    if job is None:
        return None
    _lock_job_owner(db, job.owner_user_id)
    if _active_owner_jobs(db, job.owner_user_id, now) >= settings.max_active_jobs_per_user:
        return None
    claim = _claim_job_row(
        job,
        worker_id=worker_id,
        now=now,
        settings=settings,
        processing_status=JobStatus.optional_enhancing,
    )
    task = db.scalar(select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id))
    if task is None or task.status not in {"queued", "processing"}:
        job.status = JobStatus.failed_final
        job.error_code = "ai_enhancement_missing"
        job.completed_at = now
        _clear_lease(job)
        return None
    task.status = "processing"
    task.updated_at = now
    db.flush()
    return claim


def claim_ai_job_by_id(
    db: Session,
    job_id: str,
    *,
    worker_id: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> JobClaim | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    _finalize_exhausted_leases(db, now)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
    if job is None or job.kind != "ai_enhancement" or job.attempts >= job.max_attempts:
        return None
    due = job.available_at if job.available_at.tzinfo else job.available_at.replace(tzinfo=UTC)
    lease_until = job.lease_until
    if lease_until is not None and lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=UTC)
    claimable = job.status in (JobStatus.queued, JobStatus.failed_retryable) or (
        job.status == JobStatus.optional_enhancing and lease_until is not None and lease_until < now
    )
    if not claimable or due > now:
        return None
    _lock_job_owner(db, job.owner_user_id)
    if _active_owner_jobs(db, job.owner_user_id, now) >= settings.max_active_jobs_per_user:
        return None
    claim = _claim_job_row(
        job,
        worker_id=worker_id,
        now=now,
        settings=settings,
        processing_status=JobStatus.optional_enhancing,
    )
    task = db.scalar(select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id))
    if task is None or task.status not in {"queued", "processing"}:
        job.status = JobStatus.failed_final
        job.error_code = "ai_enhancement_missing"
        job.completed_at = now
        _clear_lease(job)
        return None
    task.status = "processing"
    task.updated_at = now
    db.flush()
    return claim


def claim_job_by_id(
    db: Session,
    job_id: str,
    *,
    worker_id: str,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> JobClaim | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == job_id).with_for_update())
    if job is None or job.attempts >= job.max_attempts:
        return None
    if job.kind == "ai_enhancement":
        return None
    due = job.available_at
    if due.tzinfo is None:
        due = due.replace(tzinfo=UTC)
    lease_until = job.lease_until
    if lease_until is not None and lease_until.tzinfo is None:
        lease_until = lease_until.replace(tzinfo=UTC)
    claimable = job.status in (JobStatus.queued, JobStatus.failed_retryable) or (
        job.status == JobStatus.baseline_processing
        and lease_until is not None
        and lease_until < now
    )
    if not claimable or due > now:
        return None
    _lock_job_owner(db, job.owner_user_id)
    if _active_owner_jobs(db, job.owner_user_id, now) >= settings.max_active_jobs_per_user:
        return None
    claim = _claim_job_row(job, worker_id=worker_id, now=now, settings=settings)
    db.flush()
    return claim


def heartbeat_job(
    db: Session,
    claim: JobClaim,
    *,
    progress: int,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> bool:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == claim.job_id).with_for_update())
    if (
        job is None
        or job.status not in (JobStatus.baseline_processing, JobStatus.optional_enhancing)
        or job.lease_token != claim.lease_token
        or job.cancel_requested_at is not None
    ):
        return False
    job.progress = max(job.progress, min(progress, 95))
    job.heartbeat_at = now
    job.lease_until = now + timedelta(seconds=settings.job_lease_seconds)
    return True


def mark_job_failure(
    db: Session,
    claim: JobClaim,
    *,
    error_code: str,
    error: str,
    retryable: bool = True,
    now: datetime | None = None,
    settings: Settings | None = None,
) -> ProcessingJob | None:
    settings = settings or get_settings()
    now = now or datetime.now(UTC)
    job = db.scalar(select(ProcessingJob).where(ProcessingJob.id == claim.job_id).with_for_update())
    if job is None or job.lease_token != claim.lease_token:
        return None
    if job.status == JobStatus.canceled or job.cancel_requested_at is not None:
        job.status = JobStatus.canceled
        job.canceled_at = job.canceled_at or now
        job.progress = 0
    elif not retryable or job.attempts >= job.max_attempts:
        job.status = JobStatus.failed_final
        job.completed_at = now
    else:
        job.status = JobStatus.failed_retryable
        delay = settings.job_retry_base_seconds * (2 ** max(job.attempts - 1, 0))
        job.available_at = now + timedelta(seconds=min(delay, 300))
    job.error_code = error_code[:64]
    job.error = error[:1000]
    _clear_lease(job)
    if job.kind == "ai_enhancement":
        task = db.scalar(
            select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id)
        )
        if task is not None:
            task.status = "failed" if job.status == JobStatus.failed_final else "queued"
            task.error_code = job.error_code
            task.updated_at = now
            db.execute(
                update(AiMediaGrant)
                .where(
                    AiMediaGrant.enhancement_task_id == task.id,
                    AiMediaGrant.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
    return job


def cancel_job(
    db: Session,
    *,
    actor: User,
    job_id: str,
    now: datetime | None = None,
) -> ProcessingJob:
    now = now or datetime.now(UTC)
    job = job_for_owner(db, actor, job_id, lock=True)
    if job.status in (JobStatus.ready, JobStatus.failed_final, JobStatus.canceled):
        raise JobFlowError("job_cannot_be_canceled")
    job.cancel_requested_at = now
    job.status = JobStatus.canceled
    job.canceled_at = now
    job.progress = 0
    _clear_lease(job)
    if job.kind == "ai_enhancement":
        task = db.scalar(
            select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id)
        )
        if task is not None:
            task.status = "canceled"
            task.updated_at = now
            db.execute(
                update(AiMediaGrant)
                .where(
                    AiMediaGrant.enhancement_task_id == task.id,
                    AiMediaGrant.revoked_at.is_(None),
                )
                .values(revoked_at=now)
            )
    return job


def retry_job(
    db: Session,
    *,
    actor: User,
    job_id: str,
    now: datetime | None = None,
) -> ProcessingJob:
    now = now or datetime.now(UTC)
    job = job_for_owner(db, actor, job_id, lock=True)
    if job.status not in (JobStatus.failed_retryable, JobStatus.failed_final):
        raise JobFlowError("job_cannot_be_retried")
    if job.status == JobStatus.failed_final:
        job.attempts = 0
    job.status = JobStatus.queued
    job.available_at = now
    job.progress = 0
    job.completed_at = None
    job.cancel_requested_at = None
    job.canceled_at = None
    job.error_code = None
    job.error = None
    _clear_lease(job)
    if job.kind == "ai_enhancement":
        task = db.scalar(
            select(AiEnhancementTask).where(AiEnhancementTask.processing_job_id == job.id)
        )
        if task is not None:
            task.status = "queued"
            task.error_code = None
            task.updated_at = now
    return job
