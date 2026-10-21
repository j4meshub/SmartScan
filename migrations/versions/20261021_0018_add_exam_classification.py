"""增加版本关联试卷分类与用户取消建议证据。

Revision ID: 20261021_0018
Revises: 20261020_0017
Create Date: 2026-10-21
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261021_0018"
down_revision: str | None = "20261020_0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("scan_pages") as batch:
        batch.add_column(sa.Column("exam_classification_status", sa.String(24), nullable=True))
        batch.add_column(sa.Column("exam_result_version", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("exam_classifier_version", sa.String(96), nullable=True))
        batch.add_column(sa.Column("exam_prediction", sa.String(16), nullable=True))
        batch.add_column(sa.Column("exam_probability", sa.Float(), nullable=True))
        batch.add_column(sa.Column("exam_confidence_band", sa.String(16), nullable=True))
        batch.add_column(sa.Column("exam_recommendation", sa.String(24), nullable=True))
        batch.add_column(sa.Column("exam_details", sa.Text(), nullable=True))
        batch.add_column(
            sa.Column("exam_suggestion_dismissed_result_version", sa.Integer(), nullable=True)
        )
        batch.add_column(
            sa.Column("exam_suggestion_dismissed_by_user_id", sa.String(36), nullable=True)
        )
        batch.add_column(
            sa.Column("exam_suggestion_dismissed_at", sa.DateTime(timezone=True), nullable=True)
        )
        batch.add_column(
            sa.Column("exam_suggestion_dismissal_reason", sa.String(160), nullable=True)
        )
        batch.add_column(sa.Column("exam_updated_at", sa.DateTime(timezone=True), nullable=True))

    op.execute(
        "UPDATE scan_pages SET exam_classification_status = 'legacy', exam_updated_at = updated_at"
    )
    with op.batch_alter_table("scan_pages") as batch:
        batch.alter_column(
            "exam_classification_status", existing_type=sa.String(24), nullable=False
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_classification_status",
            "exam_classification_status IN ('pending', 'ready', 'disabled', 'stale', 'legacy')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_result_version",
            "exam_result_version IS NULL OR exam_result_version >= 0",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_prediction",
            "exam_prediction IS NULL OR exam_prediction IN ('ordinary', 'exam')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_probability",
            "exam_probability IS NULL OR (exam_probability >= 0 AND exam_probability <= 1)",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_confidence_band",
            "exam_confidence_band IS NULL OR exam_confidence_band IN ('low', 'medium', 'high')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_recommendation",
            "exam_recommendation IS NULL OR "
            "exam_recommendation IN ('ordinary', 'ask', 'suggest_cleanup')",
        )
        batch.create_check_constraint(
            "ck_scan_pages_exam_dismissed_result_version",
            "exam_suggestion_dismissed_result_version IS NULL OR "
            "exam_suggestion_dismissed_result_version >= 0",
        )


def downgrade() -> None:
    with op.batch_alter_table("scan_pages") as batch:
        batch.drop_constraint("ck_scan_pages_exam_dismissed_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_recommendation", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_confidence_band", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_probability", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_prediction", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_result_version", type_="check")
        batch.drop_constraint("ck_scan_pages_exam_classification_status", type_="check")
        batch.drop_column("exam_updated_at")
        batch.drop_column("exam_suggestion_dismissal_reason")
        batch.drop_column("exam_suggestion_dismissed_at")
        batch.drop_column("exam_suggestion_dismissed_by_user_id")
        batch.drop_column("exam_suggestion_dismissed_result_version")
        batch.drop_column("exam_details")
        batch.drop_column("exam_recommendation")
        batch.drop_column("exam_confidence_band")
        batch.drop_column("exam_probability")
        batch.drop_column("exam_prediction")
        batch.drop_column("exam_classifier_version")
        batch.drop_column("exam_result_version")
        batch.drop_column("exam_classification_status")
