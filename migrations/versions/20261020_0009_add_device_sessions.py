"""增加设备会话元数据与轮换刷新令牌。

Revision ID: 20261020_0009
Revises: 20261020_0008
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0009"
down_revision: str | None = "20261020_0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.batch_alter_table("sessions") as batch:
        batch.add_column(sa.Column("device_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("device_name", sa.String(length=100), nullable=True))
        batch.add_column(sa.Column("platform", sa.String(length=32), nullable=True))
        batch.add_column(sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.execute(
        "UPDATE sessions SET device_id = 'legacy:' || id, "
        "device_name = '旧版客户端', platform = 'legacy', last_seen_at = created_at"
    )
    with op.batch_alter_table("sessions") as batch:
        batch.alter_column("device_id", existing_type=sa.String(length=64), nullable=False)
        batch.alter_column("device_name", existing_type=sa.String(length=100), nullable=False)
        batch.alter_column("platform", existing_type=sa.String(length=32), nullable=False)
        batch.alter_column("last_seen_at", existing_type=sa.DateTime(timezone=True), nullable=False)
        batch.create_index("ix_sessions_device_id", ["device_id"], unique=False)
    op.create_table(
        "refresh_tokens",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("session_id", sa.String(length=36), nullable=False),
        sa.Column("token_hash", sa.String(length=64), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("revoked_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("replaced_by_id", sa.String(length=36), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["session_id"], ["sessions.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["replaced_by_id"], ["refresh_tokens.id"], ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("token_hash"),
    )
    op.create_index("ix_refresh_tokens_session_id", "refresh_tokens", ["session_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_refresh_tokens_session_id", table_name="refresh_tokens")
    op.drop_table("refresh_tokens")
    with op.batch_alter_table("sessions") as batch:
        batch.drop_index("ix_sessions_device_id")
        batch.drop_column("last_seen_at")
        batch.drop_column("platform")
        batch.drop_column("device_name")
        batch.drop_column("device_id")
