"""增加账号删除请求与手机号复用隔离。

Revision ID: 20261020_0010
Revises: 20261020_0009
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0010"
down_revision: str | None = "20261020_0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

account_deletion_status = sa.Enum(
    "pending",
    "cleanup_pending",
    "completed",
    "canceled",
    name="accountdeletionstatus",
)


def upgrade() -> None:
    op.create_table(
        "account_deletion_requests",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", account_deletion_status, nullable=False),
        sa.Column("requested_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("execute_after", sa.DateTime(timezone=True), nullable=False),
        sa.Column("processing_started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("canceled_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("last_error", sa.String(length=64), nullable=True),
        sa.Column("resource_counts", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", name="uq_account_deletion_user"),
    )
    op.create_index(
        "ix_account_deletion_requests_user_id",
        "account_deletion_requests",
        ["user_id"],
    )
    op.create_index(
        "ix_account_deletion_requests_status",
        "account_deletion_requests",
        ["status"],
    )
    op.create_index(
        "ix_account_deletion_requests_execute_after",
        "account_deletion_requests",
        ["execute_after"],
    )
    op.create_table(
        "phone_reuse_quarantines",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("phone_hmac", sa.String(length=64), nullable=False),
        sa.Column("hmac_key_id", sa.String(length=64), nullable=False),
        sa.Column("deletion_request_id", sa.String(length=36), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_phone_reuse_quarantines_phone_hmac",
        "phone_reuse_quarantines",
        ["phone_hmac"],
        unique=True,
    )
    op.create_index(
        "ix_phone_reuse_quarantines_deletion_request_id",
        "phone_reuse_quarantines",
        ["deletion_request_id"],
    )
    op.create_index(
        "ix_phone_reuse_quarantines_expires_at",
        "phone_reuse_quarantines",
        ["expires_at"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_phone_reuse_quarantines_expires_at",
        table_name="phone_reuse_quarantines",
    )
    op.drop_index(
        "ix_phone_reuse_quarantines_deletion_request_id",
        table_name="phone_reuse_quarantines",
    )
    op.drop_index(
        "ix_phone_reuse_quarantines_phone_hmac",
        table_name="phone_reuse_quarantines",
    )
    op.drop_table("phone_reuse_quarantines")
    op.drop_index(
        "ix_account_deletion_requests_execute_after",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_status",
        table_name="account_deletion_requests",
    )
    op.drop_index(
        "ix_account_deletion_requests_user_id",
        table_name="account_deletion_requests",
    )
    op.drop_table("account_deletion_requests")
    if op.get_bind().dialect.name == "postgresql":
        account_deletion_status.drop(op.get_bind(), checkfirst=True)
