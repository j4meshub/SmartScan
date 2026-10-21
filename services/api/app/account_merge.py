from __future__ import annotations

import hashlib
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import (
    AccountMergeAudit,
    ExportArtifact,
    JobStatus,
    PageResult,
    ProcessingJob,
    ProjectDeletion,
    ProjectDeletionStatus,
    Role,
    ScanExport,
    ScanPage,
    ScanProject,
    UploadChunk,
    UploadSession,
    UploadStatus,
    User,
    UserIdentity,
    UserStatus,
    VerifiedPhone,
)
from .security import phone_hmac_candidates
from .session_service import revoke_user_sessions
from .sms import consume_sms_challenge


class AccountMergeError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


@dataclass(frozen=True)
class AccountMergeOutcome:
    audit: AccountMergeAudit
    replayed: bool = False


@dataclass(frozen=True)
class _FileReference:
    record: object
    attribute: str
    expected_sha256: str | None
    required: bool


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        while block := source.read(1024 * 1024):
            digest.update(block)
    return digest.hexdigest()


def _safe_absolute(root: Path, relative: str) -> Path:
    absolute = (root / relative).resolve()
    resolved_root = root.resolve()
    if resolved_root not in absolute.parents:
        raise AccountMergeError("account_merge_file_path_invalid")
    return absolute


def _canonical_relative(relative: str, source_id: str, canonical_id: str) -> str:
    path = PurePosixPath(relative.replace("\\", "/"))
    if len(path.parts) < 3 or path.parts[:2] != ("users", source_id):
        raise AccountMergeError("account_merge_file_path_invalid")
    if any(part in ("", ".", "..") for part in path.parts):
        raise AccountMergeError("account_merge_file_path_invalid")
    return str(PurePosixPath("users", canonical_id, *path.parts[2:]))


def _copy_verified_file(
    source: Path,
    destination: Path,
    *,
    expected_sha256: str | None,
) -> bool:
    source_digest = _file_sha256(source)
    if expected_sha256 is not None and source_digest != expected_sha256:
        raise AccountMergeError("account_merge_file_hash_mismatch")
    if destination.exists():
        if _file_sha256(destination) != source_digest:
            raise AccountMergeError("account_merge_file_conflict")
        return False
    destination.parent.mkdir(parents=True, exist_ok=True)
    incoming = destination.with_name(f".{destination.name}.merge-{uuid.uuid4().hex}.incoming")
    try:
        shutil.copy2(source, incoming)
        if _file_sha256(incoming) != source_digest:
            raise AccountMergeError("account_merge_file_copy_failed", status_code=500)
        os.replace(incoming, destination)
    finally:
        incoming.unlink(missing_ok=True)
    return True


def _prepare_file_copies(
    references: list[_FileReference],
    *,
    source_id: str,
    canonical_id: str,
    settings: Settings,
    created_destinations: list[Path],
    sources_to_remove: list[Path],
) -> None:
    copied: dict[str, tuple[str, Path, Path]] = {}
    for reference in references:
        relative = str(getattr(reference.record, reference.attribute))
        canonical_relative = _canonical_relative(relative, source_id, canonical_id)
        source = _safe_absolute(settings.storage_root, relative)
        destination = _safe_absolute(settings.storage_root, canonical_relative)
        previous = copied.get(relative)
        if previous is None:
            if not source.is_file():
                if reference.required:
                    raise AccountMergeError("account_merge_file_missing")
            else:
                created = _copy_verified_file(
                    source,
                    destination,
                    expected_sha256=reference.expected_sha256,
                )
                if created:
                    created_destinations.append(destination)
                sources_to_remove.append(source)
            copied[relative] = (canonical_relative, source, destination)
        elif previous[0] != canonical_relative:
            raise AccountMergeError("account_merge_file_path_conflict")
        setattr(reference.record, reference.attribute, canonical_relative)


def _load_merge_resources(
    db: Session, source_id: str, canonical_id: str
) -> tuple[
    list[UserIdentity],
    list[ScanProject],
    list[ScanPage],
    list[PageResult],
    list[UploadSession],
    list[UploadChunk],
    list[ProcessingJob],
    list[ScanExport],
    list[ExportArtifact],
]:
    identities = list(
        db.scalars(
            select(UserIdentity)
            .where(UserIdentity.user_id.in_((source_id, canonical_id)))
            .with_for_update()
        )
    )
    projects = list(
        db.scalars(
            select(ScanProject).where(ScanProject.owner_user_id == source_id).with_for_update()
        )
    )
    pages = list(
        db.scalars(select(ScanPage).where(ScanPage.owner_user_id == source_id).with_for_update())
    )
    page_results = list(
        db.scalars(
            select(PageResult).where(PageResult.owner_user_id == source_id).with_for_update()
        )
    )
    uploads = list(
        db.scalars(
            select(UploadSession)
            .where(UploadSession.owner_user_id.in_((source_id, canonical_id)))
            .with_for_update()
        )
    )
    source_upload_ids = [item.id for item in uploads if item.owner_user_id == source_id]
    chunks = (
        list(
            db.scalars(
                select(UploadChunk)
                .where(UploadChunk.upload_id.in_(source_upload_ids))
                .with_for_update()
            )
        )
        if source_upload_ids
        else []
    )
    jobs = list(
        db.scalars(
            select(ProcessingJob).where(ProcessingJob.owner_user_id == source_id).with_for_update()
        )
    )
    exports = list(
        db.scalars(
            select(ScanExport).where(ScanExport.owner_user_id == source_id).with_for_update()
        )
    )
    artifacts = list(
        db.scalars(
            select(ExportArtifact)
            .where(ExportArtifact.owner_user_id == source_id)
            .with_for_update()
        )
    )
    return identities, projects, pages, page_results, uploads, chunks, jobs, exports, artifacts


def merge_accounts(
    db: Session,
    *,
    actor: User,
    phone: str,
    sms_challenge_id: str,
    sms_code: str,
    idempotency_key: str,
    settings: Settings | None = None,
) -> AccountMergeOutcome:
    settings = settings or get_settings()
    existing = db.scalar(
        select(AccountMergeAudit).where(AccountMergeAudit.idempotency_key == idempotency_key)
    )
    if existing is not None:
        if actor.id != existing.canonical_user_id:
            raise AccountMergeError("account_merge_conflict")
        return AccountMergeOutcome(existing, replayed=True)

    verification = consume_sms_challenge(
        db,
        challenge_id=sms_challenge_id,
        phone=phone,
        code=sms_code,
        purpose="account_merge",
    )
    if not verification.accepted:
        raise AccountMergeError(verification.reason, status_code=400)

    digests = list(phone_hmac_candidates(phone, settings=settings).values())
    phone_rows = list(
        db.scalars(
            select(VerifiedPhone).where(VerifiedPhone.phone_hmac.in_(digests)).with_for_update()
        )
    )
    user_ids = sorted({row.user_id for row in phone_rows})
    if len(user_ids) != 2 or actor.id not in user_ids:
        raise AccountMergeError("account_merge_conflict")
    users = list(db.scalars(select(User).where(User.id.in_(user_ids)).with_for_update()))
    if len(users) != 2 or any(
        user.status != UserStatus.active or user.role != Role.user for user in users
    ):
        raise AccountMergeError("account_merge_conflict")
    canonical, source = sorted(users, key=lambda item: (item.created_at, item.id))

    (
        identities,
        projects,
        pages,
        page_results,
        uploads,
        chunks,
        jobs,
        exports,
        artifacts,
    ) = _load_merge_resources(db, source.id, canonical.id)
    source_identities = [item for item in identities if item.user_id == source.id]
    canonical_providers = {item.provider for item in identities if item.user_id == canonical.id}
    if any(item.provider in canonical_providers for item in source_identities):
        raise AccountMergeError("account_merge_identity_conflict")
    source_uploads = [item for item in uploads if item.owner_user_id == source.id]
    canonical_keys = {
        item.idempotency_key for item in uploads if item.owner_user_id == canonical.id
    }
    if any(item.idempotency_key in canonical_keys for item in source_uploads):
        raise AccountMergeError("account_merge_upload_conflict")
    if any(item.status == UploadStatus.pending for item in source_uploads):
        raise AccountMergeError("account_merge_upload_pending")
    if any(
        item.status in (JobStatus.baseline_processing, JobStatus.optional_enhancing)
        for item in jobs
    ):
        raise AccountMergeError("account_merge_job_running")
    pending_cleanup = db.scalar(
        select(ProjectDeletion.id).where(
            ProjectDeletion.owner_user_id.in_((source.id, canonical.id)),
            ProjectDeletion.status == ProjectDeletionStatus.cleanup_pending,
        )
    )
    if pending_cleanup is not None:
        raise AccountMergeError("account_merge_project_cleanup_pending")

    source_phone = next(row for row in phone_rows if row.user_id == source.id)
    references: list[_FileReference] = []
    for page in pages:
        references.append(_FileReference(page, "original_path", page.sha256, True))
        if page.book_logical_source_path:
            references.append(_FileReference(page, "book_logical_source_path", None, True))
        if page.processed_path and not any(
            result.file_path == page.processed_path for result in page_results
        ):
            references.append(_FileReference(page, "processed_path", None, True))
    for result in page_results:
        references.append(_FileReference(result, "file_path", result.sha256, True))
    for artifact in artifacts:
        references.append(_FileReference(artifact, "file_path", artifact.sha256, True))
    upload_by_id = {item.id: item for item in source_uploads}
    for chunk in chunks:
        upload = upload_by_id[chunk.upload_id]
        references.append(
            _FileReference(
                chunk,
                "relative_path",
                chunk.sha256,
                upload.status == UploadStatus.pending,
            )
        )

    created_destinations: list[Path] = []
    sources_to_remove: list[Path] = []
    try:
        _prepare_file_copies(
            references,
            source_id=source.id,
            canonical_id=canonical.id,
            settings=settings,
            created_destinations=created_destinations,
            sources_to_remove=sources_to_remove,
        )
        result_path_by_page_version = {
            (result.page_id, result.version): result.file_path for result in page_results
        }
        for page in pages:
            active_path = result_path_by_page_version.get((page.id, page.active_result_version))
            if active_path is not None:
                page.processed_path = active_path
        for identity in source_identities:
            identity.user_id = canonical.id
            if identity.provider == "local":
                canonical.username = identity.provider_subject
                canonical.password_hash = identity.credential_hash or canonical.password_hash
        for project in projects:
            project.owner_user_id = canonical.id
        for page in pages:
            page.owner_user_id = canonical.id
        for result in page_results:
            result.owner_user_id = canonical.id
        for upload in source_uploads:
            upload.owner_user_id = canonical.id
        for job in jobs:
            job.owner_user_id = canonical.id
        for export in exports:
            export.owner_user_id = canonical.id
        for artifact in artifacts:
            artifact.owner_user_id = canonical.id
        db.delete(source_phone)
        now = datetime.now(UTC)
        revoke_user_sessions(db, source.id)
        revoke_user_sessions(db, canonical.id)
        source.status = UserStatus.deleted
        source.deleted_at = now
        resource_counts = {
            "identities": len(source_identities),
            "projects": len(projects),
            "pages": len(pages),
            "page_results": len(page_results),
            "uploads": len(source_uploads),
            "chunks": len(chunks),
            "jobs": len(jobs),
            "exports": len(exports),
            "export_artifacts": len(artifacts),
            "files": len(sources_to_remove),
        }
        audit = AccountMergeAudit(
            idempotency_key=idempotency_key,
            source_user_id=source.id,
            canonical_user_id=canonical.id,
            initiator_user_id=actor.id,
            rule="same_verified_phone_earliest_user",
            result="completed",
            resource_counts=json.dumps(resource_counts, sort_keys=True, separators=(",", ":")),
            created_at=now,
        )
        db.add(audit)
        db.commit()
    except AccountMergeError:
        db.rollback()
        for destination in reversed(created_destinations):
            destination.unlink(missing_ok=True)
        raise
    except Exception as exc:
        db.rollback()
        for destination in reversed(created_destinations):
            destination.unlink(missing_ok=True)
        raise AccountMergeError("account_merge_failed", status_code=500) from exc

    for source_path in sources_to_remove:
        try:
            source_path.unlink(missing_ok=True)
        except OSError:
            # 数据库已提交且目标副本已校验，此时保留源副本比返回失败或误删更安全。
            pass
    return AccountMergeOutcome(audit)
