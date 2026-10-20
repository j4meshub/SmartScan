"""拆分登录身份与已验证手机号，并无损回填现有账号。

Revision ID: 20261020_0003
Revises: 20261020_0002
Create Date: 2026-10-20
"""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

import sqlalchemy as sa
from alembic import op

revision: str = "20261020_0003"
down_revision: str | None = "20261020_0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _backfill_existing_accounts() -> None:
    connection = op.get_bind()
    duplicate = (
        connection.execute(
            sa.text(
                "SELECT user_id, provider, COUNT(*) AS identity_count FROM user_identities "
                "GROUP BY user_id, provider HAVING COUNT(*) > 1"
            )
        )
        .mappings()
        .first()
    )
    if duplicate is not None:
        raise RuntimeError(
            f"用户 {duplicate['user_id']} 的 {duplicate['provider']} 登录身份重复，停止自动迁移"
        )
    users = connection.execute(
        sa.text(
            "SELECT id, username, password_hash, phone_hmac, phone_masked, created_at "
            "FROM users ORDER BY id"
        )
    ).mappings()
    now = datetime.now(UTC)
    for user in users:
        identities = (
            connection.execute(
                sa.text(
                    "SELECT id, provider_subject FROM user_identities "
                    "WHERE user_id = :user_id AND provider = 'local'"
                ),
                {"user_id": user["id"]},
            )
            .mappings()
            .all()
        )
        if len(identities) > 1:
            raise RuntimeError(f"用户 {user['id']} 存在多个本地登录身份，停止自动迁移")
        timestamp = user["created_at"] or now
        if identities:
            identity = identities[0]
            if identity["provider_subject"] != user["username"]:
                raise RuntimeError(f"用户 {user['id']} 的本地身份与用户名不一致，停止自动迁移")
            connection.execute(
                sa.text(
                    "UPDATE user_identities SET credential_hash = :credential_hash, "
                    "created_at = COALESCE(created_at, verified_at, :created_at) WHERE id = :id"
                ),
                {
                    "credential_hash": user["password_hash"],
                    "created_at": timestamp,
                    "id": identity["id"],
                },
            )
        else:
            connection.execute(
                sa.text(
                    "INSERT INTO user_identities "
                    "(id, user_id, provider, provider_subject, credential_hash, "
                    "verified_at, last_login_at, created_at) "
                    "VALUES (:id, :user_id, 'local', :username, :credential_hash, "
                    ":verified_at, NULL, :created_at)"
                ),
                {
                    "id": str(uuid.uuid4()),
                    "user_id": user["id"],
                    "username": user["username"],
                    "credential_hash": user["password_hash"],
                    "verified_at": timestamp,
                    "created_at": timestamp,
                },
            )

        if user["phone_masked"] == "not-bound":
            continue
        connection.execute(
            sa.text(
                "INSERT INTO verified_phones "
                "(id, user_id, phone_hmac, phone_masked, verification_source, "
                "verified_at, created_at) "
                "VALUES (:id, :user_id, :phone_hmac, :phone_masked, 'legacy', "
                ":verified_at, :created_at)"
            ),
            {
                "id": str(uuid.uuid4()),
                "user_id": user["id"],
                "phone_hmac": user["phone_hmac"],
                "phone_masked": user["phone_masked"],
                "verified_at": timestamp,
                "created_at": timestamp,
            },
        )


def upgrade() -> None:
    op.create_table(
        "verified_phones",
        sa.Column("id", sa.String(length=36), nullable=False),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("phone_hmac", sa.String(length=64), nullable=False),
        sa.Column("phone_masked", sa.String(length=32), nullable=False),
        sa.Column("verification_source", sa.String(length=32), nullable=False),
        sa.Column("verified_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("phone_hmac", name="uq_verified_phone_hmac"),
        sa.UniqueConstraint("user_id", name="uq_verified_phone_user"),
    )
    with op.batch_alter_table("user_identities") as batch:
        batch.add_column(sa.Column("credential_hash", sa.String(length=255), nullable=True))
        batch.add_column(sa.Column("created_at", sa.DateTime(timezone=True), nullable=True))

    _backfill_existing_accounts()

    with op.batch_alter_table("user_identities") as batch:
        batch.alter_column(
            "created_at",
            existing_type=sa.DateTime(timezone=True),
            nullable=False,
        )
        batch.create_unique_constraint(
            "uq_identity_user_provider",
            ["user_id", "provider"],
        )


def downgrade() -> None:
    with op.batch_alter_table("user_identities") as batch:
        batch.drop_constraint("uq_identity_user_provider", type_="unique")
        batch.drop_column("created_at")
        batch.drop_column("credential_hash")
    op.drop_table("verified_phones")
