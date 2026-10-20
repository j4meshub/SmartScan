"""增加页面结果版本、质量、旋转与独立复核状态。

Revision ID: 20261020_0013
Revises: 20261020_0012
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0013"
down_revision: str | None = "20261020_0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

page_review_status = sa.Enum(
    "not_required",
    "pending",
    "confirmed",
    name="pagereviewstatus",
)


def upgrade() -> None:
    bind = op.get_bind()
    if bind.dialect.name == "postgresql":
        page_review_status.create(bind, checkfirst=True)
    with op.batch_alter_table("scan_pages") as batch:
        batch.add_column(sa.Column("original_mime_type", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("quality_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("quality_details", sa.Text(), nullable=True))
        batch.add_column(sa.Column("rotation_degrees", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("active_result_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("review_status", page_review_status, nullable=True))
        batch.add_column(sa.Column("review_reason", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("reviewed_by_user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True))
        batch.add_column(sa.Column("updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE scan_pages SET original_mime_type = CASE "
        "WHEN lower(original_path) LIKE '%.png' THEN 'image/png' "
        "WHEN lower(original_path) LIKE '%.webp' THEN 'image/webp' "
        "WHEN lower(original_path) LIKE '%.heic' THEN 'image/heic' "
        "ELSE 'image/jpeg' END, "
        "rotation_degrees = 0, active_result_version = 0, "
        "review_status = 'not_required', review_reason = quality_warning, "
        "updated_at = created_at"
    )
    op.execute(
        "UPDATE scan_pages SET review_status = 'pending' "
        "WHERE quality_warning IS NOT NULL OR id IN "
        "(SELECT page_id FROM processing_jobs WHERE status = 'needs_review')"
    )
    op.execute("UPDATE processing_jobs SET status = 'completed' WHERE status = 'needs_review'")

    with op.batch_alter_table("scan_pages") as batch:
        batch.alter_column("original_mime_type", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("rotation_degrees", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("active_result_version", existing_type=sa.Integer(), nullable=False)
        batch.alter_column("review_status", existing_type=page_review_status, nullable=False)
        batch.alter_column("updated_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_check_constraint(
            "ck_scan_pages_rotation", "rotation_degrees IN (0, 90, 180, 270)"
        )
        batch.create_check_constraint(
            "ck_scan_pages_quality_score",
            "quality_score IS NULL OR (quality_score >= 0 AND quality_score <= 100)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_active_result_version", "active_result_version >= 0"
        )
        batch.create_index("ix_scan_pages_review_status", ["review_status"], unique=False)

    op.create_table(
        "page_results",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("page_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("result_type", sa.String(length=32), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=True),
        sa.Column("size_bytes", sa.Integer(), nullable=True),
        sa.Column("rotation_degrees", sa.Integer(), nullable=False),
        sa.Column("processor_version", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("rotation_degrees IN (0, 90, 180, 270)", name="ck_page_result_rotation"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["scan_pages.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("page_id", "version", name="uq_page_result_version"),
    )
    op.create_index("ix_page_results_page_id", "page_results", ["page_id"], unique=False)
    op.create_index(
        "ix_page_results_owner_user_id", "page_results", ["owner_user_id"], unique=False
    )
    op.execute(
        "INSERT INTO page_results "
        "(id, page_id, owner_user_id, version, result_type, file_path, mime_type, "
        "sha256, size_bytes, rotation_degrees, processor_version, created_at) "
        "SELECT id, id, owner_user_id, 1, 'baseline', processed_path, mime_type, "
        "NULL, NULL, 0, 'legacy-baseline', created_at FROM scan_pages "
        "WHERE processed_path IS NOT NULL"
    )
    op.execute("UPDATE scan_pages SET active_result_version = 1 WHERE processed_path IS NOT NULL")


def downgrade() -> None:
    op.execute(
        "UPDATE processing_jobs SET status = 'needs_review' WHERE status = 'completed' "
        "AND page_id IN (SELECT id FROM scan_pages WHERE review_status = 'pending')"
    )
    op.drop_index("ix_page_results_owner_user_id", table_name="page_results")
    op.drop_index("ix_page_results_page_id", table_name="page_results")
    op.drop_table("page_results")
    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_index("ix_scan_pages_review_status")
        batch.drop_constraint("ck_scan_pages_active_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_quality_score", type_="check")
        batch.drop_constraint("ck_scan_pages_rotation", type_="check")
        batch.drop_column("updated_at")
        batch.drop_column("reviewed_at")
        batch.drop_column("reviewed_by_user_id")
        batch.drop_column("review_reason")
        batch.drop_column("review_status")
        batch.drop_column("active_result_version")
        batch.drop_column("rotation_degrees")
        batch.drop_column("quality_details")
        batch.drop_column("quality_score")
        batch.drop_column("original_mime_type")
    if op.get_bind().dialect.name == "postgresql":
        page_review_status.drop(op.get_bind(), checkfirst=True)
