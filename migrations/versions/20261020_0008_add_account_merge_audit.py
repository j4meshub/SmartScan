"""增加不可变账号合并审计。

Revision ID: 20261020_0008
Revises: 20261020_0007
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0008"
down_revision: str | None = "20261020_0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "account_merge_audits",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("idempotency_key", sa.String(length=100), nullable=False),
        sa.Column("source_user_id", sa.String(length=36), nullable=False),
        sa.Column("canonical_user_id", sa.String(length=36), nullable=False),
        sa.Column("initiator_user_id", sa.String(length=36), nullable=False),
        sa.Column("rule", sa.String(length=64), nullable=False),
        sa.Column("result", sa.String(length=20), nullable=False),
        sa.Column("resource_counts", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_account_merge_audits_source_user_id",
        "account_merge_audits",
        ["source_user_id"],
    )
    op.create_index(
        "ix_account_merge_audits_canonical_user_id",
        "account_merge_audits",
        ["canonical_user_id"],
    )
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            """
            CREATE OR REPLACE FUNCTION account_merge_audits_immutable() RETURNS trigger AS $$
            BEGIN
              RAISE EXCEPTION 'account merge audits are append-only';
            END;
            $$ LANGUAGE plpgsql
            """
        )
        op.execute(
            "CREATE TRIGGER account_merge_audits_no_mutation "
            "BEFORE UPDATE OR DELETE ON account_merge_audits "
            "FOR EACH ROW EXECUTE FUNCTION account_merge_audits_immutable()"
        )


def downgrade() -> None:
    if op.get_bind().dialect.name == "postgresql":
        op.execute(
            "DROP TRIGGER IF EXISTS account_merge_audits_no_mutation ON account_merge_audits"
        )
        op.execute("DROP FUNCTION IF EXISTS account_merge_audits_immutable()")
    op.drop_index(
        "ix_account_merge_audits_canonical_user_id",
        table_name="account_merge_audits",
    )
    op.drop_index(
        "ix_account_merge_audits_source_user_id",
        table_name="account_merge_audits",
    )
    op.drop_table("account_merge_audits")
