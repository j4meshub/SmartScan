from __future__ import annotations

from functools import lru_cache
from typing import Any

from fastapi import Body, FastAPI, HTTPException
from pydantic import ValidationError

from .network import (
    NetworkSecurityError,
    OutboundMediaReference,
    SecureProviderTransport,
)
from .providers import ProviderDefinition, ProviderRegistry, create_adapter, load_provider_registry
from .tasks import (
    StructuredTaskError,
    build_provider_request_plan,
    build_result_evidence,
    task_schema_catalog,
    validate_result,
    validate_task,
    validation_error_details,
)


@lru_cache
def get_registry() -> ProviderRegistry:
    return load_provider_registry()


@lru_cache
def get_network_transport() -> SecureProviderTransport:
    return SecureProviderTransport()


def _network_error_status(code: str) -> int:
    if code in {
        "provider_redirect_rejected",
        "provider_http_error",
        "provider_content_encoding_rejected",
        "provider_content_type_rejected",
        "provider_content_length_invalid",
        "provider_transfer_encoding_rejected",
        "provider_response_too_large",
        "provider_response_empty",
    }:
        return 502
    if code in {
        "provider_dns_resolution_failed",
        "provider_dns_no_addresses",
        "provider_transport_failed",
    }:
        return 503
    return 422


def create_app() -> FastAPI:
    application = FastAPI(title="SmartScan 可选视觉 AI 网关", version="0.3.0")

    @application.get("/health")
    def health():
        registry = get_registry()
        return {
            "status": "ok",
            "enabled": registry.enabled_count > 0,
            "provider_count": len(registry.list_descriptors()),
            "enabled_count": registry.enabled_count,
            "ready_count": registry.ready_count,
        }

    @application.get("/v1/providers")
    def list_providers():
        return {"items": get_registry().list_descriptors()}

    @application.get("/v1/providers/{provider_id}")
    def get_provider(provider_id: str):
        try:
            return get_registry().get(provider_id).descriptor()
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc

    @application.post("/v1/providers/check")
    def check_provider(payload: ProviderDefinition):
        adapter = create_adapter(payload, {})
        return {
            "accepted": True,
            "provider": adapter.descriptor(),
            "note": "configuration_only_no_network_request",
        }

    @application.get("/v1/task-schemas")
    def list_task_schemas():
        return {"items": task_schema_catalog()}

    @application.post("/v1/tasks/validate")
    def validate_structured_task(payload: dict[str, Any] = Body()):
        try:
            task = validate_task(payload)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "structured_task_invalid", "errors": validation_error_details(exc)},
            ) from exc
        return {
            "accepted": True,
            "task": task.model_dump(mode="json"),
            "note": "validation_only_no_network_request",
        }

    @application.post("/v1/tasks/{provider_id}/plan")
    def plan_structured_task(provider_id: str, payload: dict[str, Any] = Body()):
        try:
            adapter = get_registry().get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        try:
            task = validate_task(payload)
            return build_provider_request_plan(adapter, task)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={"code": "structured_task_invalid", "errors": validation_error_details(exc)},
            ) from exc
        except StructuredTaskError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            error_code = str(exc)
            status_code = 409 if error_code == "provider_disabled" else 503
            raise HTTPException(status_code=status_code, detail=error_code) from exc

    @application.post("/v1/results/{provider_id}/validate")
    def validate_structured_result(provider_id: str, payload: dict[str, Any] = Body()):
        if set(payload) != {"task", "provider_output"} or not isinstance(
            payload["provider_output"], str
        ):
            raise HTTPException(status_code=422, detail="result_validation_envelope_invalid")
        try:
            adapter = get_registry().get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        try:
            task = validate_task(payload["task"])
            result, disposition = validate_result(task, payload["provider_output"])
            evidence = build_result_evidence(adapter, task, result, disposition)
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "structured_result_invalid",
                    "errors": validation_error_details(exc),
                },
            ) from exc
        except (StructuredTaskError, TypeError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            error_code = str(exc)
            status_code = 409 if error_code == "provider_disabled" else 503
            raise HTTPException(status_code=status_code, detail=error_code) from exc
        return {"accepted": True, "evidence": evidence}

    @application.post("/v1/tasks/{provider_id}/execute")
    def execute_structured_task(provider_id: str, payload: dict[str, Any] = Body()):
        if set(payload) != {"task", "media"} or not isinstance(payload["media"], dict):
            raise HTTPException(status_code=422, detail="task_execution_envelope_invalid")
        try:
            adapter = get_registry().get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        try:
            task = validate_task(payload["task"])
            media = OutboundMediaReference.model_validate(payload["media"])
        except ValidationError as exc:
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "task_execution_invalid",
                    "errors": validation_error_details(exc),
                },
            ) from exc
        try:
            plan = build_provider_request_plan(adapter, task)
        except StructuredTaskError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        except RuntimeError as exc:
            error_code = str(exc)
            status_code = 409 if error_code == "provider_disabled" else 503
            raise HTTPException(status_code=status_code, detail=error_code) from exc
        try:
            network_result = get_network_transport().execute(adapter, task, plan, media)
        except NetworkSecurityError as exc:
            code = str(exc)
            raise HTTPException(status_code=_network_error_status(code), detail=code) from exc
        try:
            result, disposition = validate_result(task, network_result.provider_output)
            evidence = build_result_evidence(adapter, task, result, disposition)
        except (ValidationError, StructuredTaskError, TypeError) as exc:
            raise HTTPException(status_code=502, detail="provider_output_rejected") from exc
        except RuntimeError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        return {
            "accepted": True,
            "evidence": evidence,
            "network": network_result.evidence,
        }

    return application


app = create_app()
