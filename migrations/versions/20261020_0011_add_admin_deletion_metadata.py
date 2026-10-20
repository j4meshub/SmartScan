"""增加管理端删除申请来源与原因。

Revision ID: 20261020_0011
Revises: 20261020_0010
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0011"
down_revision: str | None = "20261020_0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.add_column(sa.Column("requested_by_user_id", sa.String(length=36), nullable=True))
        batch.add_column(sa.Column("request_source", sa.String(length=20), nullable=True))
        batch.add_column(sa.Column("reason", sa.String(length=500), nullable=True))
    op.execute(
        "UPDATE account_deletion_requests SET requested_by_user_id = user_id, "
        "request_source = 'self_service'"
    )
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.alter_column(
            "requested_by_user_id", existing_type=sa.String(length=36), nullable=False
        )
        batch.alter_column("request_source", existing_type=sa.String(length=20), nullable=False)
        batch.create_index(
            "ix_account_deletion_requests_requested_by_user_id",
            ["requested_by_user_id"],
            unique=False,
        )


def downgrade() -> None:
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.drop_index("ix_account_deletion_requests_requested_by_user_id")
        batch.drop_column("reason")
        batch.drop_column("request_source")
        batch.drop_column("requested_by_user_id")
