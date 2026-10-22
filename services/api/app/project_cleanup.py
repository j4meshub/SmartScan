from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath

from sqlalchemy import delete, select, update
from sqlalchemy.orm import Session

from .config import Settings, get_settings
from .models import (
    AiEnhancementTask,
    AiProviderCall,
    ExportArtifact,
    PageResult,
    ProcessingJob,
    ProjectDeletion,
    ProjectDeletionStatus,
    ScanExport,
    ScanPage,
    ScanProject,
    UploadChunk,
    UploadSession,
    User,
)


class ProjectCleanupError(RuntimeError):
    def __init__(self, code: str, status_code: int = 409):
        super().__init__(code)
        self.code = code
        self.status_code = status_code


def _validated_relative_path(relative: str, owner_user_id: str, settings: Settings) -> str:
    normalized = PurePosixPath(relative.replace("\\", "/"))
    if (
        len(normalized.parts) < 3
        or normalized.parts[:2] != ("users", owner_user_id)
        or any(part in ("", ".", "..") for part in normalized.parts)
    ):
        raise ProjectCleanupError("project_file_path_invalid", status_code=500)
    root = settings.storage_root.resolve()
    absolute = (root / Path(*normalized.parts)).resolve()
    if root not in absolute.parents:
        raise ProjectCleanupError("project_file_path_invalid", status_code=500)
    return normalized.as_posix()


def start_project_deletion(
    db: Session,
    *,
    actor: User,
    project: ScanProject,
    settings: Settings | None = None,
) -> ProjectDeletion:
    settings = settings or get_settings()
    if project.owner_user_id != actor.id:
        raise ProjectCleanupError("project_not_found", status_code=404)
    pages = list(db.scalars(select(ScanPage).where(ScanPage.project_id == project.id)))
    page_ids = [page.id for page in pages]
    results = (
        list(db.scalars(select(PageResult).where(PageResult.page_id.in_(page_ids))))
        if page_ids
        else []
    )
    uploads = list(db.scalars(select(UploadSession).where(UploadSession.project_id == project.id)))
    upload_ids = [upload.id for upload in uploads]
    chunks = (
        list(db.scalars(select(UploadChunk).where(UploadChunk.upload_id.in_(upload_ids))))
        if upload_ids
        else []
    )
    jobs = list(db.scalars(select(ProcessingJob).where(ProcessingJob.project_id == project.id)))
    ai_enhancements = list(
        db.scalars(select(AiEnhancementTask).where(AiEnhancementTask.project_id == project.id))
    )
    exports = list(db.scalars(select(ScanExport).where(ScanExport.project_id == project.id)))
    export_ids = [item.id for item in exports]
    artifacts = (
        list(db.scalars(select(ExportArtifact).where(ExportArtifact.export_id.in_(export_ids))))
        if export_ids
        else []
    )
    relative_paths = {
        *(page.original_path for page in pages),
        *(page.processed_path for page in pages if page.processed_path),
        *(page.book_logical_source_path for page in pages if page.book_logical_source_path),
        *(result.file_path for result in results),
        *(chunk.relative_path for chunk in chunks),
        *(artifact.file_path for artifact in artifacts),
    }
    manifest = sorted(_validated_relative_path(path, actor.id, settings) for path in relative_paths)
    counts = {
        "pages": len(pages),
        "page_results": len(results),
        "uploads": len(uploads),
        "chunks": len(chunks),
        "jobs": len(jobs),
        "ai_enhancements": len(ai_enhancements),
        "exports": len(exports),
        "export_artifacts": len(artifacts),
        "files": len(manifest),
    }
    deletion = ProjectDeletion(
        owner_user_id=actor.id,
        project_id=project.id,
        project_title=project.title,
        status=ProjectDeletionStatus.cleanup_pending,
        file_manifest=json.dumps(manifest, ensure_ascii=False, separators=(",", ":")),
        resource_counts=json.dumps(counts, sort_keys=True, separators=(",", ":")),
        requested_at=datetime.now(UTC),
    )
    db.add(deletion)
    db.flush()
    if artifacts:
        db.execute(
            delete(ExportArtifact).where(ExportArtifact.id.in_([item.id for item in artifacts]))
        )
    if exports:
        db.execute(delete(ScanExport).where(ScanExport.id.in_(export_ids)))
    if ai_enhancements:
        ai_enhancement_ids = [item.id for item in ai_enhancements]
        db.execute(
            update(AiProviderCall)
            .where(AiProviderCall.enhancement_task_id.in_(ai_enhancement_ids))
            .values(enhancement_task_id=None)
        )
        db.execute(delete(AiEnhancementTask).where(AiEnhancementTask.id.in_(ai_enhancement_ids)))
    if jobs:
        db.execute(delete(ProcessingJob).where(ProcessingJob.id.in_([item.id for item in jobs])))
    if chunks:
        db.execute(delete(UploadChunk).where(UploadChunk.id.in_([item.id for item in chunks])))
    if uploads:
        db.execute(delete(UploadSession).where(UploadSession.id.in_(upload_ids)))
    if results:
        db.execute(delete(PageResult).where(PageResult.id.in_([item.id for item in results])))
    if pages:
        db.execute(delete(ScanPage).where(ScanPage.id.in_(page_ids)))
    db.execute(delete(ScanProject).where(ScanProject.id == project.id))
    return deletion


def cleanup_project_files(
    db: Session,
    deletion: ProjectDeletion,
    *,
    settings: Settings | None = None,
) -> ProjectDeletion:
    settings = settings or get_settings()
    if deletion.status == ProjectDeletionStatus.completed:
        return deletion
    try:
        manifest = json.loads(deletion.file_manifest)
    except json.JSONDecodeError as exc:
        raise ProjectCleanupError("project_cleanup_manifest_invalid", status_code=500) from exc
    if not isinstance(manifest, list) or not all(isinstance(path, str) for path in manifest):
        raise ProjectCleanupError("project_cleanup_manifest_invalid", status_code=500)
    deletion.attempts += 1
    failed = False
    parents: set[Path] = set()
    for relative in manifest:
        validated = _validated_relative_path(relative, deletion.owner_user_id, settings)
        absolute = (
            settings.storage_root.resolve() / Path(*PurePosixPath(validated).parts)
        ).resolve()
        try:
            absolute.unlink(missing_ok=True)
            parents.add(absolute.parent)
        except OSError:
            failed = True
    user_root = (settings.storage_root.resolve() / "users" / deletion.owner_user_id).resolve()
    for parent in sorted(parents, key=lambda item: len(item.parts), reverse=True):
        current = parent
        while current != user_root and user_root in current.parents:
            try:
                current.rmdir()
            except OSError:
                break
            current = current.parent
    if failed:
        deletion.last_error = "project_file_cleanup_failed"
    else:
        deletion.status = ProjectDeletionStatus.completed
        deletion.completed_at = datetime.now(UTC)
        deletion.last_error = None
    db.commit()
    return deletion


def process_next_project_cleanup(
    db: Session,
    *,
    settings: Settings | None = None,
) -> ProjectDeletion | None:
    deletion = db.scalar(
        select(ProjectDeletion)
        .where(ProjectDeletion.status == ProjectDeletionStatus.cleanup_pending)
        .order_by(ProjectDeletion.requested_at)
        .limit(1)
        .with_for_update(skip_locked=True)
    )
    if deletion is None:
        return None
    return cleanup_project_files(db, deletion, settings=settings)
