"""扩展作业状态机、租约心跳与重试字段。

Revision ID: 20261020_0014
Revises: 20261020_0013
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0014"
down_revision: str | None = "20261020_0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

legacy_job_status = sa.Enum(
    "pending",
    "running",
    "completed",
    "failed",
    "needs_review",
    name="jobstatus",
)


def _status_to_v2() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE processing_jobs ALTER COLUMN status TYPE VARCHAR(32) USING status::text"
        )
        legacy_job_status.drop(bind, checkfirst=True)
    else:
        with op.batch_alter_table("processing_jobs") as batch:
            batch.alter_column(
                "status",
                existing_type=legacy_job_status,
                type_=sa.String(length=32),
                nullable=False,
            )


def _status_to_legacy() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        legacy_job_status.create(bind, checkfirst=True)
        op.execute(
            "ALTER TABLE processing_jobs ALTER COLUMN status TYPE jobstatus "
            "USING status::text::jobstatus"
        )
    else:
        with op.batch_alter_table("processing_jobs") as batch:
            batch.alter_column(
                "status",
                existing_type=sa.String(length=32),
                type_=legacy_job_status,
                nullable=False,
            )


def upgrade() -> None:
    _status_to_v2()
    with op.batch_alter_table("processing_jobs") as batch:
        batch.add_column(sa.Column("max_attempts", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("priority", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("progress", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("available_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("lease_owner", sa.String(length=128), nullable=True))
        batch.add_column(sa.Column("lease_token", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("heartbeat_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("started_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("baseline_ready_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(
            sa.Column("cancel_requested_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("error_code", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("result_version", sa.Integer(), nullable=True))

    op.execute(
        "UPDATE processing_jobs SET status = CASE status "
        "WHEN 'pending' THEN 'queued' "
        "WHEN 'running' THEN 'queued' "
        "WHEN 'completed' THEN 'ready' "
        "WHEN 'needs_review' THEN 'ready' "
        "WHEN 'failed' THEN CASE WHEN attempts >= 3 THEN 'failed_final' "
        "ELSE 'failed_retryable' END ELSE status END"
    )
    op.execute(
        "UPDATE processing_jobs SET max_attempts = 3, priority = 0, "
        "progress = CASE WHEN status = 'ready' THEN 100 ELSE 0 END, "
        "available_at = created_at, "
        "baseline_ready_at = CASE WHEN status = 'ready' THEN updated_at ELSE NULL END, "
        "completed_at = CASE WHEN status IN ('ready', 'failed_final') "
        "THEN updated_at ELSE NULL END, "
        "error_code = CASE WHEN status IN ('failed_retryable', 'failed_final') "
        "THEN 'legacy_failure' ELSE NULL END, "
        "result_version = CASE WHEN status = 'ready' THEN "
        "(SELECT active_result_version FROM scan_pages WHERE scan_pages.id = processing_jobs.page_id) "
        "ELSE NULL END, lease_until = NULL"
    )
    with op.batch_alter_table("processing_jobs") as batch:
        batch.alter_column("max_attempts", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("priority", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("progress", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("available_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_check_constraint(
            "ck_processing_jobs_progress", "progress >= 0 AND progress <= 100"
        )
        batch.create_check_constraint("ck_processing_jobs_max_attempts", "max_attempts >= 1")
        batch.create_index("ix_processing_jobs_available_at", ["available_at"], unique=False)


def downgrade() -> None:
    op.execute(
        "UPDATE processing_jobs SET status = CASE status "
        "WHEN 'queued' THEN 'pending' "
        "WHEN 'baseline_processing' THEN 'running' "
        "WHEN 'baseline_ready' THEN 'completed' "
        "WHEN 'optional_enhancing' THEN 'running' "
        "WHEN 'ready' THEN 'completed' "
        "WHEN 'failed_retryable' THEN 'pending' "
        "WHEN 'failed_final' THEN 'failed' "
        "WHEN 'canceled' THEN 'failed' ELSE status END"
    )
    with op.batch_alter_table("processing_jobs") as batch:
        batch.drop_index("ix_processing_jobs_available_at")
        batch.drop_constraint("ck_processing_jobs_max_attempts", type_="check")
        batch.drop_constraint("ck_processing_jobs_progress", type_="check")
        batch.drop_column("result_version")
        batch.drop_column("error_code")
        batch.drop_column("canceled_at")
        batch.drop_column("cancel_requested_at")
        batch.drop_column("completed_at")
        batch.drop_column("baseline_ready_at")
        batch.drop_column("started_at")
        batch.drop_column("heartbeat_at")
        batch.drop_column("lease_token")
        batch.drop_column("lease_owner")
        batch.drop_column("available_at")
        batch.drop_column("progress")
        batch.drop_column("priority")
        batch.drop_column("max_attempts")
    _status_to_legacy()
