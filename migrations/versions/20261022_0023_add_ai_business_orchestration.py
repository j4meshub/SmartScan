"""增加项目级 AI 授权与版本绑定的候选增强任务。

Revision ID: 20261022_0023
Revises: 20261022_0022
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0023"
down_revision: str | None = "20261022_0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_projects") as batch:
        batch.add_column(
            sa.Column("ai_enabled", sa.Boolean(), nullable=True, server_default=sa.false())
        )
        batch.add_column(sa.Column("ai_consent_version", sa.String(32), nullable=True))
        batch.add_column(sa.Column("ai_enabled_by_user_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("ai_enabled_at", sa.DateTime(timezone=True), nullable=True))
    op.execute("UPDATE scan_projects SET ai_enabled = FALSE WHERE ai_enabled IS NULL")
    with op.batch_alter_table("scan_projects") as batch:
        batch.alter_column(
            "ai_enabled", existing_type=sa.Boolean(), nullable=False, server_default=None
        )

    with op.batch_alter_table("page_results") as batch:
        batch.add_column(sa.Column("source_result_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("provenance", sa.Text(), nullable=True))
        batch.create_check_constraint(
            "ck_page_results_source_version",
            "source_result_version IS NULL OR source_result_version >= 1",
        )

    op.create_table(
        "ai_enhancement_tasks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "owner_user_id",
            sa.String(36),
            sa.ForeignKey("users.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "project_id",
            sa.String(36),
            sa.ForeignKey("scan_projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "page_id",
            sa.String(36),
            sa.ForeignKey("scan_pages.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "processing_job_id",
            sa.String(36),
            sa.ForeignKey("processing_jobs.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("enhancement_kind", sa.String(24), nullable=False),
        sa.Column("requested_tasks", sa.Text(), nullable=False),
        sa.Column("source_result_version", sa.Integer(), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("candidate_result", sa.Text(), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("provider_id", sa.String(64), nullable=True),
        sa.Column("model", sa.String(128), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=True),
        sa.Column("error_code", sa.String(64), nullable=True),
        sa.Column("accepted_by_user_id", sa.String(36), nullable=True),
        sa.Column("accepted_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rejected_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("page_id", "idempotency_key", name="uq_ai_enhancement_page_key"),
        sa.UniqueConstraint("processing_job_id", name="uq_ai_enhancement_processing_job"),
        sa.CheckConstraint(
            "enhancement_kind IN ('recommended', 'complex_ocr', 'exam_review', 'book_review')",
            name="ck_ai_enhancement_kind",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'processing', 'candidate_ready', 'accepted', 'rejected', "
            "'stale', 'failed', 'canceled')",
            name="ck_ai_enhancement_status",
        ),
        sa.CheckConstraint("source_result_version >= 1", name="ck_ai_enhancement_source_version"),
        sa.CheckConstraint(
            "confidence IS NULL OR (confidence >= 0 AND confidence <= 1)",
            name="ck_ai_enhancement_confidence",
        ),
    )
    op.create_index(
        "ix_ai_enhancement_tasks_owner_user_id",
        "ai_enhancement_tasks",
        ["owner_user_id"],
    )
    op.create_index("ix_ai_enhancement_tasks_project_id", "ai_enhancement_tasks", ["project_id"])
    op.create_index("ix_ai_enhancement_tasks_page_id", "ai_enhancement_tasks", ["page_id"])
    op.create_index(
        "ix_ai_enhancement_tasks_processing_job_id",
        "ai_enhancement_tasks",
        ["processing_job_id"],
    )
    op.create_index("ix_ai_enhancement_tasks_status", "ai_enhancement_tasks", ["status"])

    with op.batch_alter_table("ai_provider_calls") as batch:
        batch.add_column(sa.Column("enhancement_task_id", sa.String(36), nullable=True))
        batch.create_foreign_key(
            "fk_ai_provider_calls_enhancement_task",
            "ai_enhancement_tasks",
            ["enhancement_task_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_ai_provider_calls_enhancement_task_id",
        "ai_provider_calls",
        ["enhancement_task_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_provider_calls_enhancement_task_id", table_name="ai_provider_calls")
    with op.batch_alter_table("ai_provider_calls") as batch:
        batch.drop_constraint("fk_ai_provider_calls_enhancement_task", type_="foreignkey")
        batch.drop_column("enhancement_task_id")

    op.drop_index("ix_ai_enhancement_tasks_status", table_name="ai_enhancement_tasks")
    op.drop_index("ix_ai_enhancement_tasks_processing_job_id", table_name="ai_enhancement_tasks")
    op.drop_index("ix_ai_enhancement_tasks_page_id", table_name="ai_enhancement_tasks")
    op.drop_index("ix_ai_enhancement_tasks_project_id", table_name="ai_enhancement_tasks")
    op.drop_index("ix_ai_enhancement_tasks_owner_user_id", table_name="ai_enhancement_tasks")
    op.drop_table("ai_enhancement_tasks")

    with op.batch_alter_table("page_results") as batch:
        batch.drop_constraint("ck_page_results_source_version", type_="check")
        batch.drop_column("provenance")
        batch.drop_column("source_result_version")

    with op.batch_alter_table("scan_projects") as batch:
        batch.drop_column("ai_enabled_at")
        batch.drop_column("ai_enabled_by_user_id")
        batch.drop_column("ai_consent_version")
        batch.drop_column("ai_enabled")
