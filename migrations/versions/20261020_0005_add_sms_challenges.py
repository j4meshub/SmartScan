"""增加短信验证码挑战、尝试次数与限频索引。

Revision ID: 20261020_0005
Revises: 20261020_0004
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0005"
down_revision: str | None = "20261020_0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sms_challenges",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("phone_hmac", sa.String(length=64), nullable=False),
        sa.Column("hmac_key_id", sa.String(length=64), nullable=False),
        sa.Column("requester_ip_hash", sa.String(length=64), nullable=False),
        sa.Column("purpose", sa.String(length=32), nullable=False),
        sa.Column("code_hash", sa.String(length=64), nullable=False),
        sa.Column("provider", sa.String(length=32), nullable=False),
        sa.Column("provider_receipt", sa.String(length=128), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("consumed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index("ix_sms_challenges_phone_hmac", "sms_challenges", ["phone_hmac"])
    op.create_index(
        "ix_sms_challenges_requester_ip_hash",
        "sms_challenges",
        ["requester_ip_hash"],
    )
    op.create_index("ix_sms_challenges_created_at", "sms_challenges", ["created_at"])


def downgrade() -> None:
    op.drop_index("ix_sms_challenges_created_at", table_name="sms_challenges")
    op.drop_index("ix_sms_challenges_requester_ip_hash", table_name="sms_challenges")
    op.drop_index("ix_sms_challenges_phone_hmac", table_name="sms_challenges")
    op.drop_table("sms_challenges")
