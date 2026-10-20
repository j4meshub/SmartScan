"""增加上传取消与可重试项目文件清理。

Revision ID: 20261020_0017
Revises: 20261020_0016
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0017"
down_revision: str | None = "20261020_0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

legacy_upload_status = sa.Enum(
    "pending",
    "completed",
    "expired",
    name="uploadstatus",
)


def _status_to_string() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        op.execute(
            "ALTER TABLE upload_sessions ALTER COLUMN status TYPE VARCHAR(16) USING status::text"
        )
        legacy_upload_status.drop(bind, checkfirst=True)
    else:
        with op.batch_alter_table("upload_sessions") as batch:
            batch.alter_column(
                "status",
                existing_type=legacy_upload_status,
                type_=sa.String(length=16),
                nullable=False,
            )


def _status_to_legacy() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        legacy_upload_status.create(bind, checkfirst=True)
        op.execute(
            "ALTER TABLE upload_sessions ALTER COLUMN status TYPE uploadstatus "
            "USING status::text::uploadstatus"
        )
    else:
        with op.batch_alter_table("upload_sessions") as batch:
            batch.alter_column(
                "status",
                existing_type=sa.String(length=16),
                type_=legacy_upload_status,
                nullable=False,
            )


def upgrade() -> None:
    _status_to_string()
    op.create_table(
        "project_deletions",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("project_title", sa.String(length=160), nullable=False),
        sa.Column("status", sa.String(length=24), nullable=False),
        sa.Column("file_manifest", sa.Text(), nullable=False),
        sa.Column("resource_counts", sa.Text(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint(
            "status IN ('cleanup_pending', 'completed')", name="ck_project_deletions_status"
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("project_id", name="uq_project_deletions_project"),
    )
    op.create_index("ix_project_deletions_owner_user_id", "project_deletions", ["owner_user_id"])
    op.create_index("ix_project_deletions_status", "project_deletions", ["status"])


def downgrade() -> None:
    op.drop_index("ix_project_deletions_status", table_name="project_deletions")
    op.drop_index("ix_project_deletions_owner_user_id", table_name="project_deletions")
    op.drop_table("project_deletions")
    op.execute("UPDATE upload_sessions SET status = 'expired' WHERE status = 'canceled'")
    _status_to_legacy()
