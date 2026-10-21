"""增加 Worker 存活心跳证据。

Revision ID: 20261022_0022
Revises: 20261021_0021
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0022"
down_revision: str | None = "20261021_0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "worker_heartbeats",
        sa.Column("worker_id", sa.String(128), primary_key=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("busy_job_id", sa.String(36), nullable=True),
    )
    op.create_index(
        "ix_worker_heartbeats_heartbeat_at",
        "worker_heartbeats",
        ["heartbeat_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_worker_heartbeats_heartbeat_at", table_name="worker_heartbeats")
    op.drop_table("worker_heartbeats")
