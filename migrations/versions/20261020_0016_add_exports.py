"""增加版本化导出请求与制品。

Revision ID: 20261020_0016
Revises: 20261020_0015
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0016"
down_revision: str | None = "20261020_0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scan_exports",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("project_id", sa.String(length=36), nullable=False),
        sa.Column("format", sa.String(length=8), nullable=False),
        sa.Column("quality", sa.String(length=16), nullable=False),
        sa.Column("include_ocr_text", sa.Boolean(), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("page_count", sa.Integer(), nullable=False),
        sa.Column("ocr_pages_used", sa.Integer(), nullable=False),
        sa.Column("base_file_name", sa.String(length=160), nullable=False),
        sa.Column("page_snapshot", sa.Text(), nullable=False),
        sa.Column("processor_version", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.CheckConstraint("format IN ('jpg', 'pdf')", name="ck_scan_exports_format"),
        sa.CheckConstraint(
            "quality IN ('clear', 'balanced', 'small')", name="ck_scan_exports_quality"
        ),
        sa.CheckConstraint(
            "status IN ('generating', 'ready', 'failed')", name="ck_scan_exports_status"
        ),
        sa.CheckConstraint("page_count >= 1", name="ck_scan_exports_page_count"),
        sa.CheckConstraint(
            "ocr_pages_used >= 0 AND ocr_pages_used <= page_count",
            name="ck_scan_exports_ocr_pages_used",
        ),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["project_id"], ["scan_projects.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_scan_exports_owner_user_id", "scan_exports", ["owner_user_id"])
    op.create_index("ix_scan_exports_project_id", "scan_exports", ["project_id"])
    op.create_index("ix_scan_exports_status", "scan_exports", ["status"])

    op.create_table(
        "export_artifacts",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("export_id", sa.String(length=36), nullable=False),
        sa.Column("owner_user_id", sa.String(length=36), nullable=False),
        sa.Column("page_id", sa.String(length=36), nullable=True),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("file_name", sa.String(length=255), nullable=False),
        sa.Column("file_path", sa.String(length=500), nullable=False),
        sa.Column("mime_type", sa.String(length=64), nullable=False),
        sa.Column("sha256", sa.String(length=64), nullable=False),
        sa.Column("size_bytes", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("sequence >= 1", name="ck_export_artifacts_sequence"),
        sa.CheckConstraint("size_bytes >= 0", name="ck_export_artifacts_size"),
        sa.ForeignKeyConstraint(["export_id"], ["scan_exports.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["owner_user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["page_id"], ["scan_pages.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("export_id", "sequence", name="uq_export_artifact_sequence"),
    )
    op.create_index("ix_export_artifacts_export_id", "export_artifacts", ["export_id"])
    op.create_index("ix_export_artifacts_owner_user_id", "export_artifacts", ["owner_user_id"])


def downgrade() -> None:
    op.drop_index("ix_export_artifacts_owner_user_id", table_name="export_artifacts")
    op.drop_index("ix_export_artifacts_export_id", table_name="export_artifacts")
    op.drop_table("export_artifacts")
    op.drop_index("ix_scan_exports_status", table_name="scan_exports")
    op.drop_index("ix_scan_exports_project_id", table_name="scan_exports")
    op.drop_index("ix_scan_exports_owner_user_id", table_name="scan_exports")
    op.drop_table("scan_exports")
