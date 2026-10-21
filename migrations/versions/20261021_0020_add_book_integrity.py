"""增加扫书页码证据、完整性决策与版本化成册。

Revision ID: 20261021_0020
Revises: 20261021_0019
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0020"
down_revision: str | None = "20261021_0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_constraint("ck_scan_pages_book_split_status", type_="check")
        batch.create_check_constraint(
            "ck_scan_pages_book_split_status",
            "book_split_status IN "
            "('disabled', 'legacy', 'pending', 'split', 'fallback', 'retake', 'supplement')",
        )
        batch.add_column(sa.Column("book_page_number_status", sa.String(24), nullable=True))
        batch.add_column(sa.Column("book_page_number_label", sa.String(24), nullable=True))
        batch.add_column(sa.Column("book_page_number_value", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("book_page_number_kind", sa.String(12), nullable=True))
        batch.add_column(sa.Column("book_page_number_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("book_page_number_reason", sa.String(64), nullable=True))
        batch.add_column(sa.Column("book_page_number_result_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("book_expected_page_label", sa.String(24), nullable=True))
        batch.add_column(sa.Column("book_content_fingerprint", sa.String(16), nullable=True))
        batch.add_column(sa.Column("book_fingerprint_result_version", sa.Integer(), nullable=True))
        batch.add_column(
            sa.Column(
                "book_assembly_included", sa.Boolean(), nullable=True, server_default=sa.true()
            )
        )
        batch.add_column(sa.Column("book_assembly_exclusion_reason", sa.String(64), nullable=True))

    op.execute(
        "UPDATE scan_pages SET book_page_number_status = CASE "
        "WHEN book_split_status = 'disabled' THEN 'disabled' ELSE 'legacy' END, "
        "book_assembly_included = 1"
    )
    with op.batch_alter_table("scan_pages") as batch:
        batch.alter_column("book_page_number_status", existing_type=sa.String(24), nullable=False)
        batch.alter_column(
            "book_assembly_included",
            existing_type=sa.Boolean(),
            nullable=False,
            server_default=None,
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_page_number_status",
            "book_page_number_status IN "
            "('disabled', 'legacy', 'pending', 'ready', 'none', 'ambiguous', 'stale')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_page_number_kind",
            "book_page_number_kind IS NULL OR book_page_number_kind IN ('arabic', 'roman')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_page_number_confidence",
            "book_page_number_confidence IS NULL OR "
            "(book_page_number_confidence >= 0 AND book_page_number_confidence <= 1)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_page_number_result_version",
            "book_page_number_result_version IS NULL OR book_page_number_result_version >= 0",
        )
        batch.create_check_constraint(
            "ck_scan_pages_book_fingerprint_result_version",
            "book_fingerprint_result_version IS NULL OR book_fingerprint_result_version >= 0",
        )

    op.create_table(
        "book_integrity_decisions",
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
        sa.Column("issue_key", sa.String(160), nullable=False),
        sa.Column("issue_kind", sa.String(32), nullable=False),
        sa.Column("decision", sa.String(32), nullable=False),
        sa.Column("details", sa.Text(), nullable=True),
        sa.Column("decided_by_user_id", sa.String(36), nullable=False),
        sa.Column("decided_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "decision IN ('ignored', 'confirmed_absent', 'keep_both', 'exclude_duplicate')",
            name="ck_book_integrity_decisions_decision",
        ),
        sa.UniqueConstraint("project_id", "issue_key", name="uq_book_integrity_decision_issue"),
    )
    op.create_index(
        "ix_book_integrity_decisions_owner_user_id",
        "book_integrity_decisions",
        ["owner_user_id"],
    )
    op.create_index(
        "ix_book_integrity_decisions_project_id",
        "book_integrity_decisions",
        ["project_id"],
    )

    with op.batch_alter_table("scan_exports") as batch:
        batch.add_column(sa.Column("book_assembly_signature", sa.String(64), nullable=True))
        batch.add_column(sa.Column("book_assembly_revision", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("book_previous_export_id", sa.String(36), nullable=True))
        batch.create_check_constraint(
            "ck_scan_exports_book_assembly_revision",
            "book_assembly_revision IS NULL OR book_assembly_revision >= 1",
        )
        batch.create_unique_constraint(
            "uq_scan_exports_book_assembly_signature",
            ["project_id", "book_assembly_signature"],
        )
        batch.create_foreign_key(
            "fk_scan_exports_book_previous_export",
            "scan_exports",
            ["book_previous_export_id"],
            ["id"],
            ondelete="SET NULL",
        )
    op.create_index(
        "ix_scan_exports_book_assembly_signature",
        "scan_exports",
        ["book_assembly_signature"],
    )
    op.create_index(
        "ix_scan_exports_book_previous_export_id",
        "scan_exports",
        ["book_previous_export_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_scan_exports_book_previous_export_id", table_name="scan_exports")
    op.drop_index("ix_scan_exports_book_assembly_signature", table_name="scan_exports")
    with op.batch_alter_table("scan_exports") as batch:
        batch.drop_constraint("fk_scan_exports_book_previous_export", type_="foreignkey")
        batch.drop_constraint("uq_scan_exports_book_assembly_signature", type_="unique")
        batch.drop_constraint("ck_scan_exports_book_assembly_revision", type_="check")
        batch.drop_column("book_previous_export_id")
        batch.drop_column("book_assembly_revision")
        batch.drop_column("book_assembly_signature")

    op.drop_index("ix_book_integrity_decisions_project_id", table_name="book_integrity_decisions")
    op.drop_index(
        "ix_book_integrity_decisions_owner_user_id", table_name="book_integrity_decisions"
    )
    op.drop_table("book_integrity_decisions")

    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_constraint("ck_scan_pages_book_fingerprint_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_book_page_number_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_book_page_number_confidence", type_="check")
        batch.drop_constraint("ck_scan_pages_book_page_number_kind", type_="check")
        batch.drop_constraint("ck_scan_pages_book_page_number_status", type_="check")
        batch.drop_column("book_assembly_exclusion_reason")
        batch.drop_column("book_assembly_included")
        batch.drop_column("book_fingerprint_result_version")
        batch.drop_column("book_content_fingerprint")
        batch.drop_column("book_expected_page_label")
        batch.drop_column("book_page_number_result_version")
        batch.drop_column("book_page_number_reason")
        batch.drop_column("book_page_number_confidence")
        batch.drop_column("book_page_number_kind")
        batch.drop_column("book_page_number_value")
        batch.drop_column("book_page_number_label")
        batch.drop_column("book_page_number_status")
        batch.drop_constraint("ck_scan_pages_book_split_status", type_="check")
        batch.create_check_constraint(
            "ck_scan_pages_book_split_status",
            "book_split_status IN ('disabled', 'legacy', 'pending', 'split', 'fallback', 'retake')",
        )
