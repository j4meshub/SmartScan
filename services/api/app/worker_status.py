from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.orm import Session

from .models import WorkerHeartbeat


def record_worker_heartbeat(
    db: Session,
    *,
    worker_id: str,
    busy_job_id: str | None,
    now: datetime | None = None,
) -> WorkerHeartbeat:
    now = now or datetime.now(UTC)
    heartbeat = db.scalar(
        select(WorkerHeartbeat).where(WorkerHeartbeat.worker_id == worker_id).with_for_update()
    )
    if heartbeat is None:
        heartbeat = WorkerHeartbeat(
            worker_id=worker_id,
            started_at=now,
            heartbeat_at=now,
            busy_job_id=busy_job_id,
        )
        db.add(heartbeat)
    else:
        heartbeat.heartbeat_at = now
        heartbeat.busy_job_id = busy_job_id
    db.flush()
    return heartbeat
