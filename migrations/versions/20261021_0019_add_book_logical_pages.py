"""增加扫书逻辑页、去弯曲证据与单侧替换血缘。

Revision ID: 20261021_0019
Revises: 20261021_0018
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0019"
down_revision: str | None = "20261021_0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_pages") as batch:
        batch.add_column(sa.Column("book_capture_id", sa.String(36), nullable=True))
        batch.add_column(sa.Column("book_side", sa.String(8), nullable=True))
        batch.add_column(sa.Column("book_split_status", sa.String(24), nullable=True))
        batch.add_column(sa.Column("book_split_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("book_split_reason", sa.String(64), nullable=True))
        batch.add_column(sa.Column("book_spine_x", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("book_logical_source_path", sa.String(500), nullable=True))
        batch.add_column(sa.Column("book_dewarp_applied", sa.Boolean(), nullable=True))
        batch.add_column(sa.Column("book_dewarp_source_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("book_dewarp_output_score", sa.Float(), nullable=True))
        batch.add_column(sa.Column("book_dewarp_reason", sa.String(64), nullable=True))
        batch.add_column(sa.Column("book_replaced_by_page_id", sa.String(36), nullable=True))

    op.execute(
        "UPDATE scan_pages SET book_split_status = CASE "
        "WHEN EXISTS (SELECT 1 FROM scan_projects "
        "WHERE scan_projects.id = scan_pages.project_id AND scan_projects.mode = 'book') "
        "THEN 'legacy' ELSE 'disabled' END"
    )
    with op.batch_alter_table("scan_pages") as batch:
        batch.alter_column("book_split_status", existing_type=sa.String(24), nullable=False)
        batch.create_check_constraint(
            "ck_scan_pages_book_split_status",
            "book_split_status IN ('disabled', 'legacy', 'pending', 'split', 'fallback', 'retake')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_side",
            "book_side IS NULL OR book_side IN ('left', 'right', 'single')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_split_confidence",
            "book_split_confidence IS NULL OR "
            "(book_split_confidence >= 0 AND book_split_confidence <= 1)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_dewarp_source_score",
            "book_dewarp_source_score IS NULL OR "
            "(book_dewarp_source_score >= 0 AND book_dewarp_source_score <= 1)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_dewarp_output_score",
            "book_dewarp_output_score IS NULL OR "
            "(book_dewarp_output_score >= 0 AND book_dewarp_output_score <= 1)",
        )
        batch.create_unique_constraint(
            "uq_scan_pages_book_capture_side", ["book_capture_id", "book_side"]
        )
        batch.create_unique_constraint(
            "uq_scan_pages_book_replaced_by", ["book_replaced_by_page_id"]
        )
        batch.create_foreign_key(
            "fk_scan_pages_book_replaced_by",
            "scan_pages",
            ["book_replaced_by_page_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index("ix_scan_pages_book_capture_id", "scan_pages", ["book_capture_id"])
    op.create_index(
        "ix_scan_pages_book_replaced_by_page_id",
        "scan_pages",
        ["book_replaced_by_page_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_pages_book_replaced_by_page_id", table_name="scan_pages")
    op.drop_index("ix_scan_pages_book_capture_id", table_name="scan_pages")
    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_constraint("fk_scan_pages_book_replaced_by", type_="foreignkey")
        batch.drop_constraint("uq_scan_pages_book_replaced_by", type_="unique")
        batch.drop_constraint("uq_scan_pages_book_capture_side", type_="unique")
        batch.drop_constraint("ck_scan_pages_book_dewarp_output_score", type_="check")
        batch.drop_constraint("ck_scan_pages_book_dewarp_source_score", type_="check")
        batch.drop_constraint("ck_scan_pages_book_split_confidence", type_="check")
        batch.drop_constraint("ck_scan_pages_book_side", type_="check")
        batch.drop_constraint("ck_scan_pages_book_split_status", type_="check")
        batch.drop_column("book_replaced_by_page_id")
        batch.drop_column("book_dewarp_reason")
        batch.drop_column("book_dewarp_output_score")
        batch.drop_column("book_dewarp_source_score")
        batch.drop_column("book_dewarp_applied")
        batch.drop_column("book_logical_source_path")
        batch.drop_column("book_spine_x")
        batch.drop_column("book_split_reason")
        batch.drop_column("book_split_confidence")
        batch.drop_column("book_split_status")
        batch.drop_column("book_side")
        batch.drop_column("book_capture_id")
