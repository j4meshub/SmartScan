from __future__ import annotations

import importlib
import logging
import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine, select
from sqlalchemy.orm import sessionmaker

from services.api.app.database import Base
from services.api.app.models import AiProviderAttempt, AiProviderCall, AiProviderState

AI_GATEWAY_ROOT = Path(__file__).parents[1] / "services" / "ai-gateway"
sys.path.insert(0, str(AI_GATEWAY_ROOT))

network = importlib.import_module("app.network")
providers = importlib.import_module("app.providers")
reliability = importlib.import_module("app.reliability")
tasks = importlib.import_module("app.tasks")

NOW = datetime(2026, 10, 21, 12, 0, tzinfo=UTC)
TASK_ID = "10000000-0000-4000-8000-000000000001"
PAGE_ID = "20000000-0000-4000-8000-000000000002"
MEDIA_TOKEN = "AbCdEfGhIjKlMnOpQrStUvWxYz012345"


def provider_definition(**changes):
    payload = {
        "id": "vision-reliable",
        "display_name": "可靠性测试模型",
        "kind": "public_vlm",
        "api_style": "openai_responses",
        "enabled": True,
        "base_url": "https://vision.example/v1",
        "api_key_env": "VISION_API_KEY",
        "model": "vision-1",
        "capabilities": ["image_classification"],
        "media_url_prefixes": ["https://media.example/ai/"],
    }
    payload.update(changes)
    return providers.ProviderDefinition.model_validate(payload)


def adapter(**changes):
    return providers.create_adapter(
        provider_definition(**changes), {"VISION_API_KEY": "never-return-this-secret"}
    )


def task():
    return tasks.validate_task(
        {
            "schema_version": "1.0",
            "task_id": TASK_ID,
            "task_type": "classify_page",
            "context": {
                "page_id": PAGE_ID,
                "source_result_version": 1,
                "media": {
                    "asset_id": "30000000-0000-4000-8000-000000000003",
                    "sha256": "a" * 64,
                    "mime_type": "image/jpeg",
                    "width": 100,
                    "height": 200,
                },
                "locale": "zh-CN",
            },
            "constraints": {"temperature": 0, "max_output_tokens": 128},
        }
    )


def media():
    return network.OutboundMediaReference.model_validate(
        {
            "access_token": MEDIA_TOKEN,
            "byte_size": 100,
            "sha256": "a" * 64,
            "mime_type": "image/jpeg",
            "expires_at": NOW + timedelta(minutes=10),
        }
    )


@pytest.fixture
def session_factory(tmp_path: Path):
    engine = create_engine(f"sqlite:///{(tmp_path / 'ai-reliability.db').as_posix()}")
    Base.metadata.create_all(engine)
    factory = sessionmaker(bind=engine, expire_on_commit=False)
    try:
        yield factory
    finally:
        engine.dispose()


def successful_result(provider_id: str):
    return network.SecureNetworkResult(
        provider_output=b"{}",
        evidence=network.NetworkSecurityEvidence(
            provider_id=provider_id,
            request_body_bytes=512,
            response_body_bytes=128,
        ),
    )


class SequencedTransport:
    def __init__(self, outcomes: list[object]) -> None:
        self.outcomes = outcomes
        self.timeouts: list[float] = []

    def execute(self, adapter, task, plan, media, timeout_seconds):
        self.timeouts.append(timeout_seconds)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def test_reliability_configuration_rejects_budget_that_cannot_cover_one_call() -> None:
    with pytest.raises(ValidationError, match="worst-case call"):
        provider_definition(
            max_retries=1,
            max_cost_per_request_usd="0.10",
            daily_cost_limit_usd="0.19",
        )


def test_timeout_retries_once_and_persists_conservative_cost(session_factory) -> None:
    selected = adapter(timeout_seconds=12, max_retries=1, max_cost_per_request_usd="0.025")
    timeout = network.NetworkSecurityError(
        "provider_timeout",
        retryable=True,
        counts_toward_circuit=True,
        request_sent=True,
    )
    transport = SequencedTransport([timeout, successful_result(selected.definition.id)])
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    executor = reliability.ReliableProviderExecutor(store, transport)
    structured_task = task()
    plan = tasks.build_provider_request_plan(selected, structured_task)

    pending = executor.execute_network(selected, structured_task, plan, media())
    executor.finish_success(
        selected,
        structured_task,
        pending.call_id,
        pending.attempts,
        pending.duration_ms,
        pending.result.evidence.request_body_bytes,
        pending.result.evidence.response_body_bytes,
        pending.charged_cost_microusd,
    )

    assert pending.attempts == 2
    assert transport.timeouts == [12.0, 12.0]
    with session_factory() as session:
        call = session.get(AiProviderCall, pending.call_id)
        attempts = session.scalars(
            select(AiProviderAttempt)
            .where(AiProviderAttempt.call_id == pending.call_id)
            .order_by(AiProviderAttempt.attempt_number)
        ).all()
        state = session.get(AiProviderState, selected.definition.id)
    assert call is not None
    assert call.status == "succeeded"
    assert call.attempt_count == 2
    assert call.charged_cost_microusd == 50_000
    assert [item.outcome for item in attempts] == ["failed", "succeeded"]
    assert state is not None and state.circuit_state == "closed"


def test_auth_failure_opens_circuit_immediately(session_factory) -> None:
    selected = adapter()
    auth_error = network.NetworkSecurityError(
        "provider_auth_rejected", immediate_circuit_open=True, request_sent=True
    )
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    executor = reliability.ReliableProviderExecutor(store, SequencedTransport([auth_error]))
    structured_task = task()
    plan = tasks.build_provider_request_plan(selected, structured_task)

    with pytest.raises(network.NetworkSecurityError, match="provider_auth_rejected"):
        executor.execute_network(selected, structured_task, plan, media())
    with pytest.raises(reliability.ReliabilityError, match="ai_circuit_open"):
        store.admit_call(selected.definition, structured_task.task_type.value)


def test_failure_threshold_allows_one_half_open_probe_then_recovers(session_factory) -> None:
    current = [NOW]
    definition = provider_definition(
        circuit_failure_threshold=2,
        circuit_open_seconds=30,
        max_retries=0,
    )
    store = reliability.ReliabilityStore(session_factory, clock=lambda: current[0])

    for _ in range(2):
        failed_call = store.admit_call(definition, "classify_page")
        store.finish_call(
            definition,
            failed_call,
            error_code="provider_http_5xx",
            counts_toward_circuit=True,
        )
    with pytest.raises(reliability.ReliabilityError, match="ai_circuit_open"):
        store.admit_call(definition, "classify_page")

    current[0] += timedelta(seconds=31)
    probe = store.admit_call(definition, "classify_page")
    with pytest.raises(reliability.ReliabilityError, match="ai_circuit_open"):
        store.admit_call(definition, "classify_page")
    store.finish_call(definition, probe, error_code=None)

    recovered = store.admit_call(definition, "classify_page")
    assert recovered != probe


def test_rate_limited_retry_still_records_original_provider_failure(session_factory) -> None:
    selected = adapter(
        requests_per_minute=1,
        max_retries=1,
        circuit_failure_threshold=1,
    )
    timeout = network.NetworkSecurityError(
        "provider_timeout",
        retryable=True,
        counts_toward_circuit=True,
        request_sent=True,
    )
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    executor = reliability.ReliableProviderExecutor(store, SequencedTransport([timeout]))
    structured_task = task()

    with pytest.raises(reliability.ReliabilityError, match="ai_rate_limit_exceeded"):
        executor.execute_network(
            selected,
            structured_task,
            tasks.build_provider_request_plan(selected, structured_task),
            media(),
        )

    status = store.status(selected.definition)
    assert status["circuit_state"] == "open"
    assert status["consecutive_failures"] == 1


def test_expired_circuit_does_not_enter_half_open_when_budget_rejects(session_factory) -> None:
    current = [NOW]
    definition = provider_definition(
        max_retries=0,
        max_cost_per_request_usd="0.05",
        daily_cost_limit_usd="0.05",
        circuit_failure_threshold=1,
        circuit_open_seconds=30,
    )
    store = reliability.ReliabilityStore(session_factory, clock=lambda: current[0])
    failed = store.admit_call(definition, "classify_page")
    attempt_id, _ = store.start_attempt(definition, failed)
    store.finish_attempt(failed, attempt_id, error_code="provider_http_5xx")
    store.finish_call(definition, failed, error_code="provider_http_5xx")

    current[0] += timedelta(seconds=31)
    with pytest.raises(reliability.ReliabilityError, match="ai_daily_cost_limit_exceeded"):
        store.admit_call(definition, "classify_page")

    with session_factory() as session:
        state = session.get(AiProviderState, definition.id)
    assert state is not None
    assert state.circuit_state == "open"
    assert state.half_open_lease_until is None


def test_local_security_rejection_does_not_accumulate_circuit_failures(session_factory) -> None:
    selected = adapter(circuit_failure_threshold=1, max_retries=0)
    local_error = network.NetworkSecurityError("media_sha256_mismatch")
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    executor = reliability.ReliableProviderExecutor(store, SequencedTransport([local_error]))
    structured_task = task()

    with pytest.raises(network.NetworkSecurityError, match="media_sha256_mismatch"):
        executor.execute_network(
            selected,
            structured_task,
            tasks.build_provider_request_plan(selected, structured_task),
            media(),
        )

    status = store.status(selected.definition)
    assert status["circuit_state"] == "closed"
    assert status["consecutive_failures"] == 0
    assert status["charged_cost_microusd_today"] == 0
    assert status["attempts_last_minute"] == 0


def test_concurrency_rate_and_daily_budget_gates_share_database_state(session_factory) -> None:
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    concurrency = provider_definition(concurrency_limit=1, max_retries=0)
    active_call = store.admit_call(concurrency, "classify_page")
    with pytest.raises(reliability.ReliabilityError, match="ai_concurrency_limit_exceeded"):
        store.admit_call(concurrency, "classify_page")
    store.finish_call(concurrency, active_call, error_code=None)

    rate = provider_definition(id="rate-provider", requests_per_minute=1, max_retries=1)
    rate_call = store.admit_call(rate, "classify_page")
    attempt_id, _ = store.start_attempt(rate, rate_call)
    store.finish_attempt(rate_call, attempt_id, error_code="provider_timeout")
    with pytest.raises(reliability.ReliabilityError, match="ai_rate_limit_exceeded"):
        store.start_attempt(rate, rate_call)

    budget = provider_definition(
        id="budget-provider",
        max_retries=0,
        max_cost_per_request_usd="0.05",
        daily_cost_limit_usd="0.05",
    )
    budget_call = store.admit_call(budget, "classify_page")
    budget_attempt, _ = store.start_attempt(budget, budget_call)
    store.finish_attempt(budget_call, budget_attempt, error_code=None)
    store.finish_call(budget, budget_call, error_code=None)
    with pytest.raises(reliability.ReliabilityError, match="ai_daily_cost_limit_exceeded"):
        store.admit_call(budget, "classify_page")


def test_expired_lease_releases_slot_and_counts_failure(session_factory) -> None:
    current = [NOW]
    definition = provider_definition(concurrency_limit=1, circuit_failure_threshold=2)
    store = reliability.ReliabilityStore(session_factory, clock=lambda: current[0])
    expired_call = store.admit_call(definition, "classify_page")

    current[0] += timedelta(seconds=reliability.CALL_LEASE_SECONDS + 1)
    replacement = store.admit_call(definition, "classify_page")

    assert replacement != expired_call
    with session_factory() as session:
        expired = session.get(AiProviderCall, expired_call)
    assert expired is not None
    assert expired.status == "expired"
    assert expired.error_code == "ai_call_lease_expired"


def test_structured_log_excludes_task_media_and_credentials(session_factory, caplog) -> None:
    selected = adapter(max_retries=0)
    structured_task = task()
    store = reliability.ReliabilityStore(session_factory, clock=lambda: NOW)
    executor = reliability.ReliableProviderExecutor(
        store, SequencedTransport([successful_result(selected.definition.id)])
    )

    with caplog.at_level(logging.INFO, logger="smartscan.ai.reliability"):
        pending = executor.execute_network(
            selected,
            structured_task,
            tasks.build_provider_request_plan(selected, structured_task),
            media(),
        )
        executor.finish_success(
            selected,
            structured_task,
            pending.call_id,
            pending.attempts,
            pending.duration_ms,
            pending.result.evidence.request_body_bytes,
            pending.result.evidence.response_body_bytes,
            pending.charged_cost_microusd,
        )

    assert selected.definition.id in caplog.text
    assert TASK_ID not in caplog.text
    assert PAGE_ID not in caplog.text
    assert MEDIA_TOKEN not in caplog.text
    assert "never-return-this-secret" not in caplog.text
