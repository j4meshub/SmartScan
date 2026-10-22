from __future__ import annotations

from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import FileResponse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from .ai_business import (
    AI_CONSENT_VERSION,
    AI_ENHANCEMENT_KINDS,
    AI_TASK_TYPES,
    AI_TRANSMISSION_NOTICE_CODE,
    AiBusinessError,
    accept_enhancement,
    configure_project_ai,
    create_enhancement,
    enhancement_view,
    reject_enhancement,
)
from .ai_media import resolve_media_grant
from .audit import record_audit
from .database import get_db
from .dependencies import current_user
from .models import AiEnhancementTask, ScanPage, ScanProject, User
from .policies import can_read_data
from .repositories import page_for_actor, project_for_actor
from .schemas import (
    AiCapabilitiesView,
    AiEnhancementCreate,
    AiEnhancementView,
    ProjectAiSettingsUpdate,
    ProjectView,
)

router = APIRouter()


@router.get("/v1/ai-media", include_in_schema=False)
def read_ai_media(
    access_token: str | None = Header(
        None,
        alias="X-SmartScan-AI-Media-Token",
    ),
    db: Session = Depends(get_db),
):
    resolved = (
        resolve_media_grant(db, access_token=access_token) if access_token is not None else None
    )
    if resolved is None:
        db.commit()
        raise HTTPException(status_code=404, detail="ai_media_not_found")
    grant, absolute = resolved
    db.commit()
    return FileResponse(
        absolute,
        media_type=grant.mime_type,
        headers={
            "Cache-Control": "private, no-store, max-age=0",
            "Content-Security-Policy": "default-src 'none'",
            "X-Content-Type-Options": "nosniff",
        },
    )


def _raise_business(db: Session, exc: AiBusinessError) -> None:
    if exc.persist:
        db.commit()
    else:
        db.rollback()
    raise HTTPException(status_code=exc.status_code, detail=exc.code) from exc


def _deny_owner_mutation(
    db: Session,
    request: Request,
    actor: User,
    *,
    candidate: ScanProject | ScanPage | AiEnhancementTask | None,
    action: str,
    object_type: str,
    object_id: str,
) -> None:
    if candidate is not None and candidate.owner_user_id != actor.id:
        record_audit(
            db,
            request,
            actor,
            action,
            object_type,
            object_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail=f"{object_type} not found")


@router.get("/v1/ai/capabilities", response_model=AiCapabilitiesView)
def get_ai_capabilities(_: User = Depends(current_user)) -> AiCapabilitiesView:
    return AiCapabilitiesView(
        available=False,
        business_orchestration_ready=True,
        consent_version=AI_CONSENT_VERSION,
        transmission_notice_code=AI_TRANSMISSION_NOTICE_CODE,
        enhancement_kinds=list(AI_ENHANCEMENT_KINDS),
        task_types=list(AI_TASK_TYPES),
    )


@router.put("/v1/projects/{project_id}/ai-settings", response_model=ProjectView)
def put_project_ai_settings(
    project_id: str,
    payload: ProjectAiSettingsUpdate,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanProject, project_id)
    _deny_owner_mutation(
        db,
        request,
        user,
        candidate=candidate,
        action="change_project_ai_settings",
        object_type="project",
        object_id=project_id,
    )
    project = project_for_actor(db, user, project_id)
    try:
        configure_project_ai(
            db,
            project=project,
            actor=user,
            enabled=payload.enabled,
            consent_version=payload.consent_version,
        )
    except AiBusinessError as exc:
        _raise_business(db, exc)
    record_audit(
        db,
        request,
        user,
        "change_project_ai_settings",
        "project",
        project.id,
        project.owner_user_id,
    )
    db.commit()
    db.refresh(project)
    return project


@router.post(
    "/v1/pages/{page_id}/ai-enhancements",
    response_model=AiEnhancementView,
    status_code=202,
)
def create_page_ai_enhancement(
    page_id: str,
    payload: AiEnhancementCreate,
    request: Request,
    idempotency_key: str = Header(
        ...,
        alias="Idempotency-Key",
        min_length=16,
        max_length=100,
        pattern=r"^[A-Za-z0-9_.:-]+$",
    ),
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanPage, page_id)
    _deny_owner_mutation(
        db,
        request,
        user,
        candidate=candidate,
        action="create_ai_enhancement",
        object_type="page",
        object_id=page_id,
    )
    page = page_for_actor(db, user, page_id)
    try:
        creation = create_enhancement(
            db,
            page=page,
            actor=user,
            enhancement_kind=payload.enhancement_kind,
            source_result_version=payload.source_result_version,
            idempotency_key=idempotency_key,
        )
        record_audit(
            db,
            request,
            user,
            "replay_ai_enhancement" if creation.replayed else "create_ai_enhancement",
            "ai_enhancement",
            creation.task.id,
            creation.task.owner_user_id,
        )
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        existing = db.scalar(
            select(AiEnhancementTask).where(
                AiEnhancementTask.page_id == page_id,
                AiEnhancementTask.idempotency_key == idempotency_key,
            )
        )
        if (
            existing is None
            or existing.owner_user_id != user.id
            or existing.enhancement_kind != payload.enhancement_kind
            or existing.source_result_version != payload.source_result_version
        ):
            raise HTTPException(status_code=409, detail="ai_idempotency_conflict") from exc
        record_audit(
            db,
            request,
            user,
            "replay_ai_enhancement",
            "ai_enhancement",
            existing.id,
            existing.owner_user_id,
        )
        db.commit()
        db.refresh(existing)
        return enhancement_view(existing)
    except AiBusinessError as exc:
        _raise_business(db, exc)
    db.refresh(creation.task)
    return enhancement_view(creation.task)


@router.get(
    "/v1/pages/{page_id}/ai-enhancements",
    response_model=list[AiEnhancementView],
)
def list_page_ai_enhancements(
    page_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    candidate = db.get(ScanPage, page_id)
    owner = db.get(User, candidate.owner_user_id) if candidate is not None else None
    if candidate is not None and (owner is None or not can_read_data(user, owner)):
        record_audit(
            db,
            request,
            user,
            "view_ai_enhancements",
            "page",
            page_id,
            candidate.owner_user_id,
            "denied",
        )
        db.commit()
        raise HTTPException(status_code=404, detail="page not found")
    page = page_for_actor(db, user, page_id)
    tasks = db.scalars(
        select(AiEnhancementTask)
        .where(AiEnhancementTask.page_id == page.id)
        .order_by(AiEnhancementTask.created_at.desc(), AiEnhancementTask.id)
    ).all()
    if page.owner_user_id != user.id:
        record_audit(
            db,
            request,
            user,
            "view_ai_enhancements",
            "page",
            page.id,
            page.owner_user_id,
        )
        db.commit()
    return [enhancement_view(task) for task in tasks]


def _mutate_candidate(
    enhancement_id: str,
    request: Request,
    user: User,
    db: Session,
    *,
    accept: bool,
) -> AiEnhancementView:
    candidate = db.get(AiEnhancementTask, enhancement_id)
    _deny_owner_mutation(
        db,
        request,
        user,
        candidate=candidate,
        action="accept_ai_enhancement" if accept else "reject_ai_enhancement",
        object_type="ai_enhancement",
        object_id=enhancement_id,
    )
    if candidate is None:
        raise HTTPException(status_code=404, detail="ai_enhancement not found")
    page = db.scalar(select(ScanPage).where(ScanPage.id == candidate.page_id).with_for_update())
    if page is None:
        raise HTTPException(status_code=404, detail="ai_enhancement not found")
    task = db.scalar(
        select(AiEnhancementTask)
        .where(AiEnhancementTask.id == enhancement_id, AiEnhancementTask.owner_user_id == user.id)
        .with_for_update()
    )
    if task is None:
        raise HTTPException(status_code=404, detail="ai_enhancement not found")
    try:
        if accept:
            accept_enhancement(db, task=task, page=page, actor=user)
        else:
            reject_enhancement(task=task, page=page, actor=user)
    except AiBusinessError as exc:
        _raise_business(db, exc)
    record_audit(
        db,
        request,
        user,
        "accept_ai_enhancement" if accept else "reject_ai_enhancement",
        "ai_enhancement",
        task.id,
        task.owner_user_id,
    )
    db.commit()
    db.refresh(task)
    return enhancement_view(task)


@router.post("/v1/ai-enhancements/{enhancement_id}/accept", response_model=AiEnhancementView)
def accept_page_ai_enhancement(
    enhancement_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return _mutate_candidate(enhancement_id, request, user, db, accept=True)


@router.post("/v1/ai-enhancements/{enhancement_id}/reject", response_model=AiEnhancementView)
def reject_page_ai_enhancement(
    enhancement_id: str,
    request: Request,
    user: User = Depends(current_user),
    db: Session = Depends(get_db),
):
    return _mutate_candidate(enhancement_id, request, user, db, accept=False)
