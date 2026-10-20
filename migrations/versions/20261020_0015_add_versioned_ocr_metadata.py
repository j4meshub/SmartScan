"""增加版本关联 OCR 元数据与安全建议名称。

Revision ID: 20261020_0015
Revises: 20261020_0014
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0015"
down_revision: str | None = "20261020_0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_projects") as batch:
        batch.add_column(sa.Column("suggested_name", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("suggested_name_source", sa.String(length=24), nullable=True))
        batch.add_column(
            sa.Column("suggested_name_updated_at", sa.DateTime(timezone=True), nullable=True)
        )

    with op.batch_alter_table("scan_pages") as batch:
        batch.add_column(sa.Column("ocr_status", sa.String(length=24), nullable=True))
        batch.add_column(sa.Column("ocr_result_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("ocr_model_version", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("ocr_confidence", sa.Float(), nullable=True))
        batch.add_column(sa.Column("ocr_rotation_degrees", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("ocr_details", sa.Text(), nullable=True))
        batch.add_column(sa.Column("ocr_title_candidate", sa.String(length=160), nullable=True))
        batch.add_column(sa.Column("ocr_error_code", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("ocr_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE scan_pages SET ocr_status = CASE "
        "WHEN ocr_text IS NOT NULL AND trim(ocr_text) <> '' THEN 'legacy' ELSE 'pending' END, "
        "ocr_result_version = CASE WHEN ocr_text IS NOT NULL AND trim(ocr_text) <> '' "
        "THEN active_result_version ELSE NULL END, "
        "ocr_model_version = CASE WHEN ocr_text IS NOT NULL AND trim(ocr_text) <> '' "
        "THEN 'legacy-unknown' ELSE NULL END, "
        "ocr_rotation_degrees = CASE WHEN ocr_text IS NOT NULL AND trim(ocr_text) <> '' "
        "THEN rotation_degrees ELSE NULL END, "
        "ocr_updated_at = CASE WHEN ocr_text IS NOT NULL AND trim(ocr_text) <> '' "
        "THEN updated_at ELSE NULL END"
    )
    with op.batch_alter_table("scan_pages") as batch:
        batch.alter_column("ocr_status", existing_type=sa.String(length=24), nullable=False)
        batch.create_check_constraint(
            "ck_scan_pages_ocr_confidence",
            "ocr_confidence IS NULL OR (ocr_confidence >= 0 AND ocr_confidence <= 1)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_ocr_rotation",
            "ocr_rotation_degrees IS NULL OR ocr_rotation_degrees IN (0, 90, 180, 270)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_ocr_status",
            "ocr_status IN ('pending', 'ready', 'disabled', 'stale', 'legacy')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_ocr_result_version",
            "ocr_result_version IS NULL OR ocr_result_version >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_constraint("ck_scan_pages_ocr_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_ocr_status", type_="check")
        batch.drop_constraint("ck_scan_pages_ocr_rotation", type_="check")
        batch.drop_constraint("ck_scan_pages_ocr_confidence", type_="check")
        batch.drop_column("ocr_updated_at")
        batch.drop_column("ocr_error_code")
        batch.drop_column("ocr_title_candidate")
        batch.drop_column("ocr_details")
        batch.drop_column("ocr_rotation_degrees")
        batch.drop_column("ocr_confidence")
        batch.drop_column("ocr_model_version")
        batch.drop_column("ocr_result_version")
        batch.drop_column("ocr_status")
    with op.batch_alter_table("scan_projects") as batch:
        batch.drop_column("suggested_name_updated_at")
        batch.drop_column("suggested_name_source")
        batch.drop_column("suggested_name")
