from __future__ import annotations

import json
import uuid
from dataclasses import dataclass
from typing import Any

from PIL import Image
from sqlalchemy import select
from sqlalchemy.orm import Session

from services.api.app.models import AiEnhancementTask, PageResult, ScanPage, ScanProject, User

COMMON_DOCUMENT_TASKS = {
    "classify_page",
    "detect_orientation",
    "extract_title",
    "extract_page_number",
    "ocr_formula",
}
_TASK_NAMESPACE = uuid.UUID("dbd74f57-59a2-4b0b-9550-e51c89f770c4")


class AiTaskBuildError(RuntimeError):
    pass


@dataclass(frozen=True)
class AiTaskContext:
    enhancement: AiEnhancementTask
    page: ScanPage
    project: ScanProject
    result: PageResult
    locale: str
    width: int
    height: int
    nearby_page_numbers: tuple[int, ...]


def load_task_context(
    db: Session,
    enhancement_id: str,
    *,
    image: Image.Image,
) -> AiTaskContext:
    enhancement = db.get(AiEnhancementTask, enhancement_id)
    if enhancement is None or enhancement.status != "processing":
        raise AiTaskBuildError("ai_enhancement_not_processing")
    page = db.get(ScanPage, enhancement.page_id)
    project = db.get(ScanProject, enhancement.project_id)
    owner = db.get(User, enhancement.owner_user_id)
    result = db.scalar(
        select(PageResult).where(
            PageResult.page_id == enhancement.page_id,
            PageResult.version == enhancement.source_result_version,
        )
    )
    if page is None or project is None or result is None:
        raise AiTaskBuildError("ai_source_missing")
    if (
        page.owner_user_id != enhancement.owner_user_id
        or project.owner_user_id != enhancement.owner_user_id
        or result.owner_user_id != enhancement.owner_user_id
        or page.active_result_version != enhancement.source_result_version
        or not project.ai_enabled
    ):
        raise AiTaskBuildError("ai_source_version_conflict")
    nearby = tuple(
        int(value)
        for value in db.scalars(
            select(ScanPage.book_page_number_value)
            .where(
                ScanPage.project_id == project.id,
                ScanPage.id != page.id,
                ScanPage.book_page_number_value.is_not(None),
            )
            .order_by(ScanPage.page_number)
            .limit(8)
        )
        if value is not None
    )
    return AiTaskContext(
        enhancement=enhancement,
        page=page,
        project=project,
        result=result,
        locale=owner.locale if owner is not None and owner.locale in {"zh-CN", "en"} else "zh-CN",
        width=image.width,
        height=image.height,
        nearby_page_numbers=nearby,
    )


def requested_common_tasks(enhancement: AiEnhancementTask) -> tuple[str, ...]:
    try:
        requested = json.loads(enhancement.requested_tasks)
    except json.JSONDecodeError as exc:
        raise AiTaskBuildError("ai_requested_tasks_invalid") from exc
    if not isinstance(requested, list) or not all(isinstance(item, str) for item in requested):
        raise AiTaskBuildError("ai_requested_tasks_invalid")
    unsupported = set(requested) - COMMON_DOCUMENT_TASKS
    if unsupported:
        raise AiTaskBuildError("ai_task_not_supported_by_worker")
    return tuple(requested)


def stable_task_id(enhancement_id: str, task_type: str) -> str:
    return str(uuid.uuid5(_TASK_NAMESPACE, f"{enhancement_id}:{task_type}"))


def build_task_payload(context: AiTaskContext, task_type: str) -> dict[str, Any]:
    if task_type not in COMMON_DOCUMENT_TASKS:
        raise AiTaskBuildError("ai_task_not_supported_by_worker")
    parameters: dict[str, Any]
    if task_type == "classify_page":
        parameters = {"allowed_labels": ["ordinary_document", "exam", "book_page", "cover"]}
    elif task_type == "detect_orientation":
        parameters = {"current_rotation_degrees": context.page.rotation_degrees}
    elif task_type == "extract_title":
        kind = {
            "document": "document",
            "exam": "exam",
            "book": "book",
        }.get(context.project.mode, "document")
        parameters = {"document_kind": kind, "max_candidates": 3}
    elif task_type == "extract_page_number":
        parameters = {
            "allowed_styles": ["arabic", "roman"],
            "nearby_numbers": list(context.nearby_page_numbers),
        }
    else:
        parameters = {"requested_blocks": ["formula", "table", "layout"]}
    if not isinstance(context.result.sha256, str) or len(context.result.sha256) != 64:
        raise AiTaskBuildError("ai_media_sha256_missing")
    return {
        "schema_version": "1.0",
        "task_id": stable_task_id(context.enhancement.id, task_type),
        "task_type": task_type,
        "context": {
            "page_id": context.page.id,
            "source_result_version": context.enhancement.source_result_version,
            "media": {
                "asset_id": context.result.id,
                "sha256": context.result.sha256,
                "mime_type": context.result.mime_type,
                "width": context.width,
                "height": context.height,
            },
            "locale": context.locale,
        },
        "parameters": parameters,
        "constraints": {
            "temperature": 0.0,
            "max_output_tokens": 4096 if task_type == "ocr_formula" else 1024,
        },
    }


def empty_checkpoint() -> dict[str, Any]:
    return {"schema_version": "1.0", "tasks": {}}


def load_checkpoint(raw: str | None) -> dict[str, Any]:
    if raw is None:
        return empty_checkpoint()
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        return empty_checkpoint()
    if (
        not isinstance(value, dict)
        or value.get("schema_version") != "1.0"
        or not isinstance(value.get("tasks"), dict)
    ):
        return empty_checkpoint()
    return value


def sanitized_evidence(evidence: dict[str, Any]) -> dict[str, Any]:
    allowed = {
        "provider_id",
        "provider_kind",
        "api_style",
        "model_version",
        "schema_version",
        "result_schema_sha256",
        "task_id",
        "task_type",
        "page_id",
        "source_result_version",
        "media_sha256",
        "disposition",
        "business_mutation_allowed",
        "execution_mode",
    }
    return {key: evidence[key] for key in allowed if key in evidence}


def validate_gateway_evidence(task: dict[str, Any], evidence: dict[str, Any]) -> dict[str, Any]:
    result = evidence.get("result")
    context = task.get("context")
    if not isinstance(result, dict) or not isinstance(context, dict):
        raise AiTaskBuildError("ai_gateway_response_invalid")
    expected = {
        "task_id": task.get("task_id"),
        "task_type": task.get("task_type"),
        "page_id": context.get("page_id"),
        "source_result_version": context.get("source_result_version"),
    }
    if any(evidence.get(key) != value for key, value in expected.items()):
        raise AiTaskBuildError("ai_gateway_evidence_mismatch")
    if (
        result.get("task_id") != expected["task_id"]
        or result.get("task_type") != expected["task_type"]
    ):
        raise AiTaskBuildError("ai_gateway_result_mismatch")
    confidence = result.get("confidence")
    if not isinstance(confidence, (int, float)) or not 0 <= float(confidence) <= 1:
        raise AiTaskBuildError("ai_gateway_response_invalid")
    return result
