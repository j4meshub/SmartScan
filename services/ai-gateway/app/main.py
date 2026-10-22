from __future__ import annotations

import secrets
from contextlib import asynccontextmanager
from functools import lru_cache
from typing import Any
from uuid import UUID

from fastapi import Body, FastAPI, HTTPException, Request
from fastapi.responses import JSONResponse
from pydantic import ValidationError

from .mock import deterministic_mock_result
from .network import (
    NetworkSecurityError,
    OutboundMediaReference,
    SecureProviderTransport,
)
from .providers import ProviderDefinition, ProviderRegistry, create_adapter, load_provider_registry
from .reliability import ReliabilityError, ReliabilityStore, ReliableProviderExecutor
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


def get_reliable_executor() -> ReliableProviderExecutor:
    from services.api.app.database import SessionLocal

    return ReliableProviderExecutor(ReliabilityStore(SessionLocal), get_network_transport())


def _internal_security() -> tuple[str, str]:
    from services.api.app.config import get_settings

    settings = get_settings()
    return settings.env, settings.ai_internal_token.get_secret_value()


def _mock_mode_enabled() -> bool:
    from services.api.app.config import get_settings

    settings = get_settings()
    return settings.env == "development" and settings.ai_mock_mode


def _network_error_status(code: str) -> int:
    if code in {
        "provider_redirect_rejected",
        "provider_http_error",
        "provider_auth_rejected",
        "provider_payment_required",
        "provider_http_5xx",
        "provider_rate_limited",
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
        "provider_timeout",
    }:
        return 503
    return 422


def _reliability_error_status(code: str) -> int:
    if code == "ai_business_context_invalid":
        return 409
    if code == "ai_circuit_open":
        return 503
    if code in {
        "ai_concurrency_limit_exceeded",
        "ai_rate_limit_exceeded",
        "ai_daily_cost_limit_exceeded",
    }:
        return 429
    return 503


@asynccontextmanager
async def lifespan(_: FastAPI):
    from services.api.app.config import get_settings
    from services.api.app.migrations import ensure_database_current, upgrade_database

    settings = get_settings()
    if settings.auto_migrate:
        upgrade_database(settings.database_url)
    else:
        ensure_database_current(settings.database_url)
    yield


def create_app() -> FastAPI:
    application = FastAPI(
        title="SmartScan 可选视觉 AI 网关",
        version="0.4.0",
        lifespan=lifespan,
    )

    @application.middleware("http")
    async def require_internal_auth(request: Request, call_next):
        if request.url.path.startswith("/v1/"):
            environment, expected = _internal_security()
            if not expected:
                if environment == "production":
                    return JSONResponse(status_code=503, content={"detail": "ai_gateway_disabled"})
            else:
                authorization = request.headers.get("authorization", "")
                supplied = authorization[7:] if authorization.startswith("Bearer ") else ""
                if not supplied or not secrets.compare_digest(supplied, expected):
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "internal_auth_required"},
                        headers={"WWW-Authenticate": "Bearer"},
                    )
        return await call_next(request)

    @application.get("/health")
    def health():
        registry = get_registry()
        return {
            "status": "ok",
            "execution_mode": "mock" if _mock_mode_enabled() else "provider",
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

    @application.get("/v1/providers/{provider_id}/runtime")
    def get_provider_runtime(provider_id: str):
        try:
            definition = get_registry().get(provider_id).definition
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        return get_reliable_executor().status(definition)

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
        if (
            not {"task", "media"}.issubset(payload)
            or set(payload) - {"task", "media", "enhancement_task_id"}
            or not isinstance(payload["media"], dict)
        ):
            raise HTTPException(status_code=422, detail="task_execution_envelope_invalid")
        try:
            adapter = get_registry().get(provider_id)
        except KeyError as exc:
            raise HTTPException(status_code=404, detail="provider_not_found") from exc
        try:
            task = validate_task(payload["task"])
            media = OutboundMediaReference.model_validate(payload["media"])
            enhancement_task_id = (
                str(UUID(payload["enhancement_task_id"]))
                if payload.get("enhancement_task_id") is not None
                else None
            )
        except (ValidationError, ValueError, TypeError) as exc:
            errors = (
                validation_error_details(exc)
                if isinstance(exc, ValidationError)
                else [{"type": "value_error", "loc": ["enhancement_task_id"]}]
            )
            raise HTTPException(
                status_code=422,
                detail={
                    "code": "task_execution_invalid",
                    "errors": errors,
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
        if _mock_mode_enabled():
            try:
                result, disposition = validate_result(task, deterministic_mock_result(task))
                evidence = build_result_evidence(adapter, task, result, disposition).model_dump(
                    mode="json"
                )
                evidence["execution_mode"] = "mock"
            except (ValidationError, StructuredTaskError, TypeError, ValueError) as exc:
                raise HTTPException(status_code=500, detail="mock_result_invalid") from exc
            return {
                "accepted": True,
                "evidence": evidence,
                "network": {"network_ready": True, "mock_mode": True},
            }
        executor = get_reliable_executor()
        try:
            pending = executor.execute_network(
                adapter,
                task,
                plan,
                media,
                enhancement_task_id=enhancement_task_id,
            )
            network_result = pending.result
        except ReliabilityError as exc:
            code = str(exc)
            raise HTTPException(
                status_code=_reliability_error_status(code),
                detail=code,
                headers={"Retry-After": "60"},
            ) from exc
        except NetworkSecurityError as exc:
            code = str(exc)
            raise HTTPException(status_code=_network_error_status(code), detail=code) from exc
        try:
            result, disposition = validate_result(task, network_result.provider_output)
            evidence = build_result_evidence(adapter, task, result, disposition)
        except (ValidationError, StructuredTaskError, TypeError) as exc:
            executor.finish_output_rejected(
                adapter,
                task,
                pending.call_id,
                pending.attempts,
                pending.duration_ms,
                network_result.evidence.request_body_bytes,
                network_result.evidence.response_body_bytes,
                pending.charged_cost_microusd,
            )
            raise HTTPException(status_code=502, detail="provider_output_rejected") from exc
        except RuntimeError as exc:
            executor.finish_output_rejected(
                adapter,
                task,
                pending.call_id,
                pending.attempts,
                pending.duration_ms,
                network_result.evidence.request_body_bytes,
                network_result.evidence.response_body_bytes,
                pending.charged_cost_microusd,
            )
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        executor.finish_success(
            adapter,
            task,
            pending.call_id,
            pending.attempts,
            pending.duration_ms,
            network_result.evidence.request_body_bytes,
            network_result.evidence.response_body_bytes,
            pending.charged_cost_microusd,
        )
        return {
            "accepted": True,
            "evidence": evidence,
            "network": network_result.evidence,
        }

    return application


app = create_app()
