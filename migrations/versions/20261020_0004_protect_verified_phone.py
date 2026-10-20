"""增加手机号认证加密、HMAC 版本和轮换元数据。

Revision ID: 20261020_0004
Revises: 20261020_0003
Create Date: 2026-10-20
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0004"
down_revision: str | None = "20261020_0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

phone_encryption_status = sa.Enum(
    "unavailable",
    "encrypted",
    name="phoneencryptionstatus",
)


def upgrade() -> None:
    phone_encryption_status.create(op.get_bind(), checkfirst=True)
    with op.batch_alter_table("verified_phones") as batch:
        batch.add_column(sa.Column("hmac_key_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("phone_ciphertext", sa.Text(), nullable=True))
        batch.add_column(sa.Column("encryption_key_id", sa.String(length=64), nullable=True))
        batch.add_column(sa.Column("encryption_status", phone_encryption_status, nullable=True))

    connection = op.get_bind()
    connection.execute(
        sa.text(
            "UPDATE verified_phones SET hmac_key_id = 'legacy-v1', "
            "encryption_status = 'unavailable'"
        )
    )

    with op.batch_alter_table("verified_phones") as batch:
        batch.alter_column(
            "hmac_key_id",
            existing_type=sa.String(length=64),
            nullable=False,
        )
        batch.alter_column(
            "encryption_status",
            existing_type=phone_encryption_status,
            nullable=False,
        )
        batch.create_check_constraint(
            "ck_verified_phone_encryption_state",
            "(encryption_status = 'unavailable' AND phone_ciphertext IS NULL "
            "AND encryption_key_id IS NULL) OR "
            "(encryption_status = 'encrypted' AND phone_ciphertext IS NOT NULL "
            "AND encryption_key_id IS NOT NULL)",
        )


def downgrade() -> None:
    with op.batch_alter_table("verified_phones") as batch:
        batch.drop_constraint("ck_verified_phone_encryption_state", type_="check")
        batch.drop_column("encryption_status")
        batch.drop_column("encryption_key_id")
        batch.drop_column("phone_ciphertext")
        batch.drop_column("hmac_key_id")
    phone_encryption_status.drop(op.get_bind(), checkfirst=True)
