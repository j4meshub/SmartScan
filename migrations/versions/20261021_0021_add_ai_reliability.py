"""增加 AI Provider 熔断、调用租约和脱敏计费证据。

Revision ID: 20261021_0021
Revises: 20261021_0020
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0021"
down_revision: str | None = "20261021_0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_provider_states",
        sa.Column("provider_id", sa.String(64), primary_key=True),
        sa.Column("circuit_state", sa.String(16), nullable=False),
        sa.Column("consecutive_failures", sa.Integer(), nullable=False),
        sa.Column("open_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("half_open_lease_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "circuit_state IN ('closed', 'open', 'half_open')",
            name="ck_ai_provider_states_circuit_state",
        ),
        sa.CheckConstraint(
            "consecutive_failures >= 0",
            name="ck_ai_provider_states_consecutive_failures",
        ),
    )
    op.create_table(
        "ai_provider_calls",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("task_type", sa.String(40), nullable=False),
        sa.Column("status", sa.String(16), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("reserved_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("charged_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("request_body_bytes", sa.Integer(), nullable=False),
        sa.Column("response_body_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('in_progress', 'succeeded', 'failed', 'rejected', 'expired')",
            name="ck_ai_provider_calls_status",
        ),
        sa.CheckConstraint("attempt_count >= 0", name="ck_ai_provider_calls_attempt_count"),
        sa.CheckConstraint(
            "reserved_cost_microusd >= 0 AND charged_cost_microusd >= 0",
            name="ck_ai_provider_calls_cost",
        ),
    )
    op.create_index("ix_ai_provider_calls_provider_id", "ai_provider_calls", ["provider_id"])
    op.create_index("ix_ai_provider_calls_status", "ai_provider_calls", ["status"])
    op.create_index("ix_ai_provider_calls_started_at", "ai_provider_calls", ["started_at"])
    op.create_index(
        "ix_ai_provider_calls_lease_expires_at", "ai_provider_calls", ["lease_expires_at"]
    )
    op.create_table(
        "ai_provider_attempts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "call_id",
            sa.String(36),
            sa.ForeignKey("ai_provider_calls.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("provider_id", sa.String(64), nullable=False),
        sa.Column("attempt_number", sa.Integer(), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("charged_cost_microusd", sa.Integer(), nullable=False),
        sa.Column("request_body_bytes", sa.Integer(), nullable=False),
        sa.Column("response_body_bytes", sa.Integer(), nullable=False),
        sa.Column("duration_ms", sa.Integer(), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.UniqueConstraint("call_id", "attempt_number", name="uq_ai_provider_attempt_number"),
        sa.CheckConstraint("attempt_number >= 1", name="ck_ai_provider_attempt_number"),
        sa.CheckConstraint(
            "outcome IN ('in_progress', 'succeeded', 'failed')",
            name="ck_ai_provider_attempts_outcome",
        ),
        sa.CheckConstraint("charged_cost_microusd >= 0", name="ck_ai_provider_attempts_cost"),
    )
    op.create_index("ix_ai_provider_attempts_call_id", "ai_provider_attempts", ["call_id"])
    op.create_index("ix_ai_provider_attempts_provider_id", "ai_provider_attempts", ["provider_id"])
    op.create_index("ix_ai_provider_attempts_started_at", "ai_provider_attempts", ["started_at"])


def downgrade() -> None:
    op.drop_index("ix_ai_provider_attempts_started_at", table_name="ai_provider_attempts")
    op.drop_index("ix_ai_provider_attempts_provider_id", table_name="ai_provider_attempts")
    op.drop_index("ix_ai_provider_attempts_call_id", table_name="ai_provider_attempts")
    op.drop_table("ai_provider_attempts")
    op.drop_index("ix_ai_provider_calls_lease_expires_at", table_name="ai_provider_calls")
    op.drop_index("ix_ai_provider_calls_started_at", table_name="ai_provider_calls")
    op.drop_index("ix_ai_provider_calls_status", table_name="ai_provider_calls")
    op.drop_index("ix_ai_provider_calls_provider_id", table_name="ai_provider_calls")
    op.drop_table("ai_provider_calls")
    op.drop_table("ai_provider_states")
