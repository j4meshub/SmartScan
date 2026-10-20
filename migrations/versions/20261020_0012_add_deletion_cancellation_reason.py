"""增加账号删除撤销原因。

Revision ID: 20261020_0012
Revises: 20261020_0011
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0012"
down_revision: str | None = "20261020_0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.add_column(sa.Column("cancellation_reason", sa.String(length=500), nullable=True))


def downgrade() -> None:
    with op.batch_alter_table("account_deletion_requests") as batch:
        batch.drop_column("cancellation_reason")
