from __future__ import annotations

import os
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

from prometheus_client import (
    REGISTRY,
    CollectorRegistry,
    Counter,
    Histogram,
    generate_latest,
    multiprocess,
)
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from .capacity import active_job_count, storage_capacity
from .config import Settings
from .models import (
    AiProviderCall,
    AiProviderState,
    AuditLog,
    JobStatus,
    PageReviewStatus,
    ProcessingJob,
    ScanPage,
    UploadSession,
    WorkerHeartbeat,
)

_multiprocess_dir = os.environ.get("PROMETHEUS_MULTIPROC_DIR")
if _multiprocess_dir:
    metrics_path = Path(_multiprocess_dir)
    if not metrics_path.is_absolute():
        raise RuntimeError("PROMETHEUS_MULTIPROC_DIR must be absolute")
    metrics_path.mkdir(parents=True, exist_ok=True)

API_REQUESTS = Counter(
    "smartscan_api_requests_total",
    "SmartScan API 请求数。",
    ("method", "route", "status"),
)
API_REQUEST_DURATION = Histogram(
    "smartscan_api_request_duration_seconds",
    "SmartScan API 请求耗时。",
    ("method", "route"),
    buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1, 2.5, 5, 10, 30),
)
UPLOAD_BYTES = Counter(
    "smartscan_upload_bytes_total",
    "已通过分片摘要校验并落盘的上传字节数。",
)
UPLOAD_REPLAYS = Counter(
    "smartscan_upload_chunk_replays_total",
    "重复提交且内容一致的分片数。",
)


def observe_api_request(method: str, route: str, status_code: int, duration: float) -> None:
    API_REQUESTS.labels(method=method, route=route, status=str(status_code)).inc()
    API_REQUEST_DURATION.labels(method=method, route=route).observe(duration)


def observe_upload_bytes(size_bytes: int) -> None:
    UPLOAD_BYTES.inc(size_bytes)


def observe_upload_replay() -> None:
    UPLOAD_REPLAYS.inc()


def _escape_label(value: object) -> str:
    return str(value).replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')


def _sample(name: str, value: float, **labels: object) -> str:
    label_text = ""
    if labels:
        rendered = ",".join(
            f'{key}="{_escape_label(item)}"' for key, item in sorted(labels.items())
        )
        label_text = "{" + rendered + "}"
    return f"{name}{label_text} {value}"


def _help(name: str, description: str, metric_type: str = "gauge") -> list[str]:
    return [f"# HELP {name} {description}", f"# TYPE {name} {metric_type}"]


def _seconds_since(value: datetime | None, now: datetime) -> float:
    if value is None:
        return 0.0
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return max((now - value).total_seconds(), 0.0)


def _database_snapshot(db: Session, settings: Settings, now: datetime) -> list[str]:
    started = time.perf_counter()
    db.scalar(select(func.count()).select_from(WorkerHeartbeat))
    probe_duration = time.perf_counter() - started
    lines = [*_help("smartscan_database_up", "数据库探测结果。")]
    lines.append(_sample("smartscan_database_up", 1))
    lines.extend(_help("smartscan_database_probe_duration_seconds", "数据库探测耗时。"))
    lines.append(_sample("smartscan_database_probe_duration_seconds", probe_duration))

    connection_count = 1
    if db.get_bind().dialect.name == "postgresql":
        connection_count = int(
            db.scalar(
                text("SELECT count(*) FROM pg_stat_activity WHERE datname = current_database()")
            )
            or 0
        )
    lines.extend(_help("smartscan_database_connections", "当前数据库连接数。"))
    lines.append(_sample("smartscan_database_connections", connection_count))

    lines.extend(_help("smartscan_jobs", "按处理状态统计的任务数。"))
    job_rows = db.execute(
        select(ProcessingJob.status, func.count()).group_by(ProcessingJob.status)
    ).all()
    for status, count in job_rows:
        status_value = status.value if hasattr(status, "value") else status
        lines.append(_sample("smartscan_jobs", int(count), status=status_value))
    queue_statuses = (JobStatus.queued, JobStatus.failed_retryable)
    oldest = db.scalar(
        select(func.min(ProcessingJob.created_at)).where(ProcessingJob.status.in_(queue_statuses))
    )
    lines.extend(_help("smartscan_queue_oldest_age_seconds", "最老待处理任务等待秒数。"))
    lines.append(_sample("smartscan_queue_oldest_age_seconds", _seconds_since(oldest, now)))
    lines.extend(_help("smartscan_active_jobs", "未结束的处理任务总数。"))
    lines.append(_sample("smartscan_active_jobs", active_job_count(db)))
    expired_leases = int(
        db.scalar(
            select(func.count())
            .select_from(ProcessingJob)
            .where(
                ProcessingJob.status == JobStatus.baseline_processing,
                ProcessingJob.lease_until < now,
            )
        )
        or 0
    )
    lines.extend(_help("smartscan_expired_worker_leases", "已过期但尚未回收的任务租约数。"))
    lines.append(_sample("smartscan_expired_worker_leases", expired_leases))

    stale_before = now - timedelta(seconds=settings.worker_stale_seconds)
    active_workers = int(
        db.scalar(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.heartbeat_at >= stale_before)
        )
        or 0
    )
    stale_workers = int(
        db.scalar(
            select(func.count())
            .select_from(WorkerHeartbeat)
            .where(WorkerHeartbeat.heartbeat_at < stale_before)
        )
        or 0
    )
    newest_heartbeat = db.scalar(select(func.max(WorkerHeartbeat.heartbeat_at)))
    lines.extend(_help("smartscan_workers", "按存活状态统计的 Worker 数。"))
    lines.append(_sample("smartscan_workers", active_workers, state="active"))
    lines.append(_sample("smartscan_workers", stale_workers, state="stale"))
    lines.extend(_help("smartscan_worker_heartbeat_age_seconds", "最新 Worker 心跳距今秒数。"))
    lines.append(
        _sample(
            "smartscan_worker_heartbeat_age_seconds",
            _seconds_since(newest_heartbeat, now),
        )
    )

    lines.extend(_help("smartscan_upload_sessions", "按状态统计的上传会话数。"))
    for status, count in db.execute(
        select(UploadSession.status, func.count()).group_by(UploadSession.status)
    ).all():
        status_value = status.value if hasattr(status, "value") else status
        lines.append(_sample("smartscan_upload_sessions", int(count), status=status_value))

    denied_since = now - timedelta(minutes=5)
    lines.extend(_help("smartscan_audit_denied_events_5m", "最近五分钟按动作统计的拒绝审计数。"))
    for action, count in db.execute(
        select(AuditLog.action, func.count())
        .where(AuditLog.result == "denied", AuditLog.created_at >= denied_since)
        .group_by(AuditLog.action)
    ).all():
        lines.append(_sample("smartscan_audit_denied_events_5m", int(count), action=action))

    lines.extend(_help("smartscan_pages_requiring_review", "按原因统计的待复核页面数。"))
    for reason, count in db.execute(
        select(ScanPage.review_reason, func.count())
        .where(ScanPage.review_status == PageReviewStatus.pending)
        .group_by(ScanPage.review_reason)
    ).all():
        lines.append(
            _sample(
                "smartscan_pages_requiring_review",
                int(count),
                reason=reason or "unspecified",
            )
        )

    since = now - timedelta(hours=24)
    lines.extend(_help("smartscan_ai_calls_24h", "最近 24 小时按状态统计的 AI 调用数。"))
    for status, count in db.execute(
        select(AiProviderCall.status, func.count())
        .where(AiProviderCall.started_at >= since)
        .group_by(AiProviderCall.status)
    ).all():
        lines.append(_sample("smartscan_ai_calls_24h", int(count), status=status))
    cost = int(
        db.scalar(
            select(func.coalesce(func.sum(AiProviderCall.charged_cost_microusd), 0)).where(
                AiProviderCall.started_at >= since
            )
        )
        or 0
    )
    lines.extend(_help("smartscan_ai_cost_microusd_24h", "最近 24 小时 AI 保守计费微美元。"))
    lines.append(_sample("smartscan_ai_cost_microusd_24h", cost))
    lines.extend(_help("smartscan_ai_provider_circuits", "按状态统计的 AI 熔断器数。"))
    for state, count in db.execute(
        select(AiProviderState.circuit_state, func.count()).group_by(AiProviderState.circuit_state)
    ).all():
        lines.append(_sample("smartscan_ai_provider_circuits", int(count), state=state))
    return lines


def render_operational_metrics(db: Session, settings: Settings) -> bytes:
    now = datetime.now(UTC)
    if _multiprocess_dir:
        registry = CollectorRegistry()
        multiprocess.MultiProcessCollector(registry)
    else:
        registry = REGISTRY
    application_metrics = generate_latest(registry).decode("utf-8").rstrip()
    lines = [application_metrics] if application_metrics else []
    try:
        lines.extend(_database_snapshot(db, settings, now))
    except Exception:
        db.rollback()
        lines.extend(_help("smartscan_database_up", "数据库探测结果。"))
        lines.append(_sample("smartscan_database_up", 0))

    try:
        capacity = storage_capacity(db, settings)
        lines.extend(_help("smartscan_storage_bytes", "存储文件系统字节数。"))
        lines.append(_sample("smartscan_storage_bytes", capacity.total_bytes, state="total"))
        lines.append(_sample("smartscan_storage_bytes", capacity.free_bytes, state="free"))
        lines.append(
            _sample(
                "smartscan_storage_bytes",
                capacity.reserved_upload_bytes,
                state="reserved_upload",
            )
        )
        lines.append(
            _sample(
                "smartscan_storage_bytes",
                capacity.required_free_bytes,
                state="required_free",
            )
        )
        lines.extend(_help("smartscan_storage_free_percent", "存储文件系统可用比例。"))
        lines.append(_sample("smartscan_storage_free_percent", capacity.free_percent))
        lines.extend(_help("smartscan_storage_protection_active", "磁盘保护是否已触发。"))
        lines.append(_sample("smartscan_storage_protection_active", int(capacity.protected)))
    except Exception:
        # 数据库中断会同时阻断未完成上传预留查询。指标端点仍需保持可抓取，
        # 并把未知容量视为已触发保护，避免数据库故障掩盖磁盘保护信号。
        lines.extend(_help("smartscan_storage_protection_active", "磁盘保护是否已触发。"))
        lines.append(_sample("smartscan_storage_protection_active", 1))

    lines.extend(_help("smartscan_capacity_limit", "当前容量保护配置。"))
    lines.append(
        _sample("smartscan_capacity_limit", settings.queue_high_water_jobs, limit="queue_jobs")
    )
    lines.append(
        _sample(
            "smartscan_capacity_limit",
            settings.max_active_jobs_per_user,
            limit="active_jobs_per_user",
        )
    )
    lines.append(
        _sample(
            "smartscan_capacity_limit",
            settings.user_storage_quota_bytes,
            limit="user_storage_bytes",
        )
    )
    return ("\n".join(lines) + "\n").encode("utf-8")
