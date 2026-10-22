from __future__ import annotations

import json
import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, sessionmaker

from services.api.app.models import (
    AiEnhancementTask,
    AiProviderAttempt,
    AiProviderCall,
    AiProviderState,
)

from .network import (
    NetworkSecurityError,
    OutboundMediaReference,
    SecureNetworkResult,
    SecureProviderTransport,
)
from .providers import BaseProviderAdapter, ProviderDefinition
from .tasks import ProviderRequestPlan, StructuredTask

logger = logging.getLogger("smartscan.ai.reliability")
CALL_LEASE_SECONDS = 360


class ReliabilityError(RuntimeError):
    """AI 可靠性门禁拒绝调用，仅携带稳定错误码。"""


@dataclass(frozen=True)
class PendingReliableResult:
    call_id: str
    attempts: int
    duration_ms: int
    charged_cost_microusd: int
    result: SecureNetworkResult


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


class ReliabilityStore:
    def __init__(
        self,
        session_factory: sessionmaker[Session],
        *,
        clock: Callable[[], datetime] | None = None,
    ) -> None:
        self._session_factory = session_factory
        self._clock = clock or (lambda: datetime.now(UTC))

    def _now(self) -> datetime:
        return _utc(self._clock())

    @staticmethod
    def _lock_provider(session: Session, provider_id: str) -> None:
        if session.bind is not None and session.bind.dialect.name == "postgresql":
            session.execute(
                text("SELECT pg_advisory_xact_lock(hashtextextended(:provider_id, 0))"),
                {"provider_id": provider_id},
            )

    @staticmethod
    def _state(session: Session, provider_id: str, now: datetime) -> AiProviderState:
        state = session.scalar(
            select(AiProviderState)
            .where(AiProviderState.provider_id == provider_id)
            .with_for_update()
        )
        if state is None:
            state = AiProviderState(
                provider_id=provider_id,
                circuit_state="closed",
                consecutive_failures=0,
                updated_at=now,
            )
            session.add(state)
            session.flush()
        return state

    def _expire_stale_calls(
        self, session: Session, provider_id: str, state: AiProviderState, now: datetime
    ) -> None:
        stale = session.scalars(
            select(AiProviderCall).where(
                AiProviderCall.provider_id == provider_id,
                AiProviderCall.status == "in_progress",
                AiProviderCall.lease_expires_at < now,
            )
        ).all()
        for call in stale:
            call.status = "expired"
            call.error_code = "ai_call_lease_expired"
            call.finished_at = now
            call.duration_ms = max(0, int((now - _utc(call.started_at)).total_seconds() * 1000))
            attempts = session.scalars(
                select(AiProviderAttempt).where(
                    AiProviderAttempt.call_id == call.id,
                    AiProviderAttempt.outcome == "in_progress",
                )
            ).all()
            for attempt in attempts:
                attempt.outcome = "failed"
                attempt.error_code = "ai_call_lease_expired"
                attempt.finished_at = now
                attempt.duration_ms = max(
                    0,
                    int((now - _utc(attempt.started_at)).total_seconds() * 1000),
                )
            state.consecutive_failures += 1
        if stale:
            state.updated_at = now

    def admit_call(
        self,
        definition: ProviderDefinition,
        task_type: str,
        *,
        enhancement_task_id: str | None = None,
        page_id: str | None = None,
        source_result_version: int | None = None,
    ) -> str:
        now = self._now()
        provider_id = definition.id
        reserve = definition.max_cost_per_request_microusd * (definition.max_retries + 1)
        with self._session_factory() as session, session.begin():
            if enhancement_task_id is not None:
                enhancement = session.get(AiEnhancementTask, enhancement_task_id)
                if (
                    enhancement is None
                    or enhancement.status != "processing"
                    or enhancement.page_id != page_id
                    or enhancement.source_result_version != source_result_version
                ):
                    raise ReliabilityError("ai_business_context_invalid")
            self._lock_provider(session, provider_id)
            state = self._state(session, provider_id, now)
            self._expire_stale_calls(session, provider_id, state, now)
            if (
                state.circuit_state == "closed"
                and state.consecutive_failures >= definition.circuit_failure_threshold
            ):
                state.circuit_state = "open"
                state.open_until = now + timedelta(seconds=definition.circuit_open_seconds)

            half_open_probe = False
            if state.circuit_state == "open":
                if state.open_until is not None and _utc(state.open_until) > now:
                    raise ReliabilityError("ai_circuit_open")
                half_open_probe = True
            elif state.circuit_state == "half_open":
                if state.half_open_lease_until is None or _utc(state.half_open_lease_until) > now:
                    raise ReliabilityError("ai_circuit_open")
                half_open_probe = True

            active = session.scalars(
                select(AiProviderCall).where(
                    AiProviderCall.provider_id == provider_id,
                    AiProviderCall.status == "in_progress",
                )
            ).all()
            if len(active) >= definition.concurrency_limit:
                raise ReliabilityError("ai_concurrency_limit_exceeded")

            day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
            charged = session.scalar(
                select(func.coalesce(func.sum(AiProviderAttempt.charged_cost_microusd), 0)).where(
                    AiProviderAttempt.provider_id == provider_id,
                    AiProviderAttempt.started_at >= day_start,
                )
            )
            active_unspent = sum(
                max(0, item.reserved_cost_microusd - item.charged_cost_microusd) for item in active
            )
            if int(charged or 0) + active_unspent + reserve > definition.daily_cost_limit_microusd:
                raise ReliabilityError("ai_daily_cost_limit_exceeded")

            if half_open_probe:
                state.circuit_state = "half_open"
                state.half_open_lease_until = now + timedelta(seconds=CALL_LEASE_SECONDS)

            call_id = str(uuid.uuid4())
            session.add(
                AiProviderCall(
                    id=call_id,
                    enhancement_task_id=enhancement_task_id,
                    provider_id=provider_id,
                    task_type=task_type,
                    status="in_progress",
                    attempt_count=0,
                    reserved_cost_microusd=reserve,
                    charged_cost_microusd=0,
                    request_body_bytes=0,
                    response_body_bytes=0,
                    started_at=now,
                    lease_expires_at=now + timedelta(seconds=CALL_LEASE_SECONDS),
                )
            )
            return call_id

    def start_attempt(self, definition: ProviderDefinition, call_id: str) -> tuple[str, int]:
        now = self._now()
        provider_id = definition.id
        with self._session_factory() as session, session.begin():
            self._lock_provider(session, provider_id)
            call = session.get(AiProviderCall, call_id)
            if call is None or call.provider_id != provider_id or call.status != "in_progress":
                raise ReliabilityError("ai_call_not_active")
            minute_start = now - timedelta(minutes=1)
            recent_attempts = session.scalar(
                select(func.count(AiProviderAttempt.id)).where(
                    AiProviderAttempt.provider_id == provider_id,
                    AiProviderAttempt.started_at >= minute_start,
                    AiProviderAttempt.charged_cost_microusd > 0,
                )
            )
            if int(recent_attempts or 0) >= definition.requests_per_minute:
                call.status = "rejected"
                call.error_code = "ai_rate_limit_exceeded"
                call.finished_at = now
                call.duration_ms = max(0, int((now - _utc(call.started_at)).total_seconds() * 1000))
                state = self._state(session, provider_id, now)
                if state.circuit_state == "half_open":
                    state.circuit_state = "open"
                    state.open_until = now + timedelta(seconds=definition.circuit_open_seconds)
                    state.half_open_lease_until = None
                raise ReliabilityError("ai_rate_limit_exceeded")

            attempt_number = call.attempt_count + 1
            attempt_id = str(uuid.uuid4())
            charge = definition.max_cost_per_request_microusd
            call.attempt_count = attempt_number
            call.charged_cost_microusd += charge
            call.lease_expires_at = now + timedelta(seconds=CALL_LEASE_SECONDS)
            session.add(
                AiProviderAttempt(
                    id=attempt_id,
                    call_id=call_id,
                    provider_id=provider_id,
                    attempt_number=attempt_number,
                    outcome="in_progress",
                    charged_cost_microusd=charge,
                    request_body_bytes=0,
                    response_body_bytes=0,
                    started_at=now,
                )
            )
            return attempt_id, attempt_number

    def finish_attempt(
        self,
        call_id: str,
        attempt_id: str,
        *,
        error_code: str | None,
        chargeable: bool = True,
        request_body_bytes: int = 0,
        response_body_bytes: int = 0,
    ) -> None:
        now = self._now()
        with self._session_factory() as session, session.begin():
            attempt = session.get(AiProviderAttempt, attempt_id)
            call = session.get(AiProviderCall, call_id)
            if attempt is None or call is None or attempt.call_id != call_id:
                raise ReliabilityError("ai_attempt_not_found")
            attempt.outcome = "failed" if error_code else "succeeded"
            attempt.error_code = error_code
            if not chargeable:
                call.charged_cost_microusd -= attempt.charged_cost_microusd
                attempt.charged_cost_microusd = 0
            attempt.request_body_bytes = request_body_bytes
            attempt.response_body_bytes = response_body_bytes
            attempt.finished_at = now
            attempt.duration_ms = max(
                0, int((now - _utc(attempt.started_at)).total_seconds() * 1000)
            )
            call.request_body_bytes += request_body_bytes
            call.response_body_bytes += response_body_bytes

    def finish_call(
        self,
        definition: ProviderDefinition,
        call_id: str,
        *,
        error_code: str | None,
        immediate_circuit_open: bool = False,
        counts_toward_circuit: bool = True,
    ) -> None:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._lock_provider(session, definition.id)
            call = session.get(AiProviderCall, call_id)
            if call is None or call.provider_id != definition.id:
                raise ReliabilityError("ai_call_not_found")
            if call.status != "in_progress":
                return
            state = self._state(session, definition.id, now)
            call.status = "failed" if error_code else "succeeded"
            call.error_code = error_code
            call.finished_at = now
            call.duration_ms = max(0, int((now - _utc(call.started_at)).total_seconds() * 1000))
            if error_code and counts_toward_circuit:
                self._apply_provider_failure(
                    state,
                    definition,
                    now,
                    immediate_circuit_open=immediate_circuit_open,
                )
            elif not error_code:
                state.circuit_state = "closed"
                state.consecutive_failures = 0
                state.open_until = None
                state.half_open_lease_until = None
            elif state.circuit_state == "half_open":
                state.circuit_state = "open"
                state.open_until = now + timedelta(seconds=definition.circuit_open_seconds)
                state.half_open_lease_until = None
            state.updated_at = now

    @staticmethod
    def _apply_provider_failure(
        state: AiProviderState,
        definition: ProviderDefinition,
        now: datetime,
        *,
        immediate_circuit_open: bool,
    ) -> None:
        state.consecutive_failures += 1
        if (
            immediate_circuit_open
            or state.circuit_state == "half_open"
            or state.consecutive_failures >= definition.circuit_failure_threshold
        ):
            state.circuit_state = "open"
            state.open_until = now + timedelta(seconds=definition.circuit_open_seconds)
            state.half_open_lease_until = None

    def record_provider_failure(
        self,
        definition: ProviderDefinition,
        *,
        immediate_circuit_open: bool,
    ) -> None:
        now = self._now()
        with self._session_factory() as session, session.begin():
            self._lock_provider(session, definition.id)
            state = self._state(session, definition.id, now)
            self._apply_provider_failure(
                state,
                definition,
                now,
                immediate_circuit_open=immediate_circuit_open,
            )
            state.updated_at = now

    def status(self, definition: ProviderDefinition) -> dict[str, object]:
        now = self._now()
        day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
        minute_start = now - timedelta(minutes=1)
        with self._session_factory() as session, session.begin():
            self._lock_provider(session, definition.id)
            state = self._state(session, definition.id, now)
            self._expire_stale_calls(session, definition.id, state, now)
            if (
                state.circuit_state == "closed"
                and state.consecutive_failures >= definition.circuit_failure_threshold
            ):
                state.circuit_state = "open"
                state.open_until = now + timedelta(seconds=definition.circuit_open_seconds)
            active = session.scalar(
                select(func.count(AiProviderCall.id)).where(
                    AiProviderCall.provider_id == definition.id,
                    AiProviderCall.status == "in_progress",
                )
            )
            attempts = session.scalar(
                select(func.count(AiProviderAttempt.id)).where(
                    AiProviderAttempt.provider_id == definition.id,
                    AiProviderAttempt.started_at >= minute_start,
                    AiProviderAttempt.charged_cost_microusd > 0,
                )
            )
            charged = session.scalar(
                select(func.coalesce(func.sum(AiProviderAttempt.charged_cost_microusd), 0)).where(
                    AiProviderAttempt.provider_id == definition.id,
                    AiProviderAttempt.started_at >= day_start,
                )
            )
            return {
                "provider_id": definition.id,
                "circuit_state": state.circuit_state,
                "consecutive_failures": state.consecutive_failures,
                "open_until": state.open_until,
                "active_calls": int(active or 0),
                "attempts_last_minute": int(attempts or 0),
                "charged_cost_microusd_today": int(charged or 0),
            }


class ReliableProviderExecutor:
    def __init__(
        self,
        store: ReliabilityStore,
        transport: SecureProviderTransport,
    ) -> None:
        self._store = store
        self._transport = transport

    @staticmethod
    def _log(
        definition: ProviderDefinition,
        task: StructuredTask,
        call_id: str,
        outcome: str,
        *,
        attempts: int,
        error_code: str | None = None,
        duration_ms: int = 0,
        request_body_bytes: int = 0,
        response_body_bytes: int = 0,
        charged_cost_microusd: int = 0,
    ) -> None:
        logger.info(
            json.dumps(
                {
                    "event": "ai_provider_call",
                    "provider_id": definition.id,
                    "task_type": task.task_type.value,
                    "call_id": call_id,
                    "outcome": outcome,
                    "attempts": attempts,
                    "error_code": error_code,
                    "duration_ms": duration_ms,
                    "request_body_bytes": request_body_bytes,
                    "response_body_bytes": response_body_bytes,
                    "charged_cost_microusd": charged_cost_microusd,
                },
                sort_keys=True,
                separators=(",", ":"),
            )
        )

    def execute_network(
        self,
        adapter: BaseProviderAdapter,
        task: StructuredTask,
        plan: ProviderRequestPlan,
        media: OutboundMediaReference,
        *,
        enhancement_task_id: str | None = None,
    ) -> PendingReliableResult:
        definition = adapter.definition
        call_id = self._store.admit_call(
            definition,
            task.task_type.value,
            enhancement_task_id=enhancement_task_id,
            page_id=str(task.context.page_id),
            source_result_version=task.context.source_result_version,
        )
        call_started = time.monotonic()
        attempts = 0
        charged_cost_microusd = 0
        last_network_error: NetworkSecurityError | None = None
        while attempts <= definition.max_retries:
            try:
                attempt_id, attempts = self._store.start_attempt(definition, call_id)
            except ReliabilityError:
                if last_network_error is not None and last_network_error.counts_toward_circuit:
                    self._store.record_provider_failure(
                        definition,
                        immediate_circuit_open=last_network_error.immediate_circuit_open,
                    )
                self._log(
                    definition,
                    task,
                    call_id,
                    "rejected",
                    attempts=attempts,
                    error_code="ai_rate_limit_exceeded",
                    duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
                    charged_cost_microusd=charged_cost_microusd,
                )
                raise
            try:
                result = self._transport.execute(
                    adapter,
                    task,
                    plan,
                    media,
                    definition.timeout_seconds,
                )
            except NetworkSecurityError as exc:
                self._store.finish_attempt(
                    call_id,
                    attempt_id,
                    error_code=exc.code,
                    chargeable=exc.request_sent,
                )
                if exc.request_sent:
                    charged_cost_microusd += definition.max_cost_per_request_microusd
                if exc.retryable and attempts <= definition.max_retries:
                    last_network_error = exc
                    continue
                self._store.finish_call(
                    definition,
                    call_id,
                    error_code=exc.code,
                    immediate_circuit_open=exc.immediate_circuit_open,
                    counts_toward_circuit=exc.counts_toward_circuit,
                )
                self._log(
                    definition,
                    task,
                    call_id,
                    "failed",
                    attempts=attempts,
                    error_code=exc.code,
                    duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
                    charged_cost_microusd=charged_cost_microusd,
                )
                raise
            evidence = result.evidence
            charged_cost_microusd += definition.max_cost_per_request_microusd
            self._store.finish_attempt(
                call_id,
                attempt_id,
                error_code=None,
                request_body_bytes=evidence.request_body_bytes,
                response_body_bytes=evidence.response_body_bytes,
            )
            return PendingReliableResult(
                call_id=call_id,
                attempts=attempts,
                duration_ms=max(0, int((time.monotonic() - call_started) * 1000)),
                charged_cost_microusd=charged_cost_microusd,
                result=result,
            )
        raise AssertionError("retry loop exhausted unexpectedly")

    def finish_success(
        self,
        adapter: BaseProviderAdapter,
        task: StructuredTask,
        call_id: str,
        attempts: int,
        duration_ms: int,
        request_body_bytes: int,
        response_body_bytes: int,
        charged_cost_microusd: int,
    ) -> None:
        self._store.finish_call(adapter.definition, call_id, error_code=None)
        self._log(
            adapter.definition,
            task,
            call_id,
            "succeeded",
            attempts=attempts,
            duration_ms=duration_ms,
            request_body_bytes=request_body_bytes,
            response_body_bytes=response_body_bytes,
            charged_cost_microusd=charged_cost_microusd,
        )

    def finish_output_rejected(
        self,
        adapter: BaseProviderAdapter,
        task: StructuredTask,
        call_id: str,
        attempts: int,
        duration_ms: int,
        request_body_bytes: int,
        response_body_bytes: int,
        charged_cost_microusd: int,
    ) -> None:
        self._store.finish_call(adapter.definition, call_id, error_code="provider_output_rejected")
        self._log(
            adapter.definition,
            task,
            call_id,
            "failed",
            attempts=attempts,
            error_code="provider_output_rejected",
            duration_ms=duration_ms,
            request_body_bytes=request_body_bytes,
            response_body_bytes=response_body_bytes,
            charged_cost_microusd=charged_cost_microusd,
        )

    def status(self, definition: ProviderDefinition) -> dict[str, object]:
        return self._store.status(definition)
