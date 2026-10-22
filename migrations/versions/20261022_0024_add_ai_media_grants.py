"""增加可撤销的 AI 单页媒体授权。

Revision ID: 20261022_0024
Revises: 20261022_0023
Create Date: 2026-10-22
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261022_0024"
down_revision: str | None = "20261022_0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ai_media_grants",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column(
            "enhancement_task_id",
            sa.String(36),
            sa.ForeignKey("ai_enhancement_tasks.id", ondelete="CASCADE"),
            nullable=False,
        ),
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
            "page_result_id",
            sa.String(36),
            sa.ForeignKey("page_results.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("source_result_version", sa.Integer(), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("mime_type", sa.String(64), nullable=False),
        sa.Column("sha256", sa.String(64), nullable=False),
        sa.Column("byte_size", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_accessed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("access_count", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("token_hash", name="uq_ai_media_grants_token_hash"),
        sa.CheckConstraint("source_result_version >= 1", name="ck_ai_media_grants_source_version"),
        sa.CheckConstraint("byte_size >= 0", name="ck_ai_media_grants_byte_size"),
    )
    for name in (
        "enhancement_task_id",
        "owner_user_id",
        "project_id",
        "page_id",
        "page_result_id",
        "expires_at",
        "revoked_at",
    ):
        op.create_index(f"ix_ai_media_grants_{name}", "ai_media_grants", [name])


def downgrade() -> None:
    op.drop_table("ai_media_grants")
