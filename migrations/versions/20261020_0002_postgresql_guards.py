"""安装 PostgreSQL 超级管理员与审计保护。

Revision ID: 20261020_0002
Revises: 20261020_0001
Create Date: 2026-10-20
"""

from collections.abc import Sequence

from alembic import op

revision: str = "20261020_0002"
down_revision: str | None = "20261020_0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute(
        "CREATE UNIQUE INDEX IF NOT EXISTS users_one_super_admin "
        "ON users ((role)) WHERE role = 'super_admin'"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION protect_super_admin() RETURNS trigger AS $$
        BEGIN
          IF OLD.role = 'super_admin' AND (
            TG_OP = 'DELETE' OR NEW.role <> 'super_admin' OR
            NEW.status <> 'active' OR NEW.username <> 'admin'
          ) THEN
            RAISE EXCEPTION 'the unique super administrator is protected';
          END IF;
          RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS users_protect_super_admin ON users")
    op.execute(
        "CREATE TRIGGER users_protect_super_admin BEFORE UPDATE OR DELETE ON users "
        "FOR EACH ROW EXECUTE FUNCTION protect_super_admin()"
    )
    op.execute(
        """
        CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
        BEGIN
          RAISE EXCEPTION 'audit logs are append-only';
        END;
        $$ LANGUAGE plpgsql
        """
    )
    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs")
    op.execute(
        "CREATE TRIGGER audit_logs_no_mutation BEFORE UPDATE OR DELETE ON audit_logs "
        "FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable()"
    )


def downgrade() -> None:
    if op.get_bind().dialect.name != "postgresql":
        return

    op.execute("DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs")
    op.execute("DROP FUNCTION IF EXISTS audit_logs_immutable()")
    op.execute("DROP TRIGGER IF EXISTS users_protect_super_admin ON users")
    op.execute("DROP FUNCTION IF EXISTS protect_super_admin()")
    op.execute("DROP INDEX IF EXISTS users_one_super_admin")
