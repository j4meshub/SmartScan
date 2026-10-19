CREATE UNIQUE INDEX IF NOT EXISTS users_one_super_admin
ON users ((role)) WHERE role = 'super_admin';

CREATE OR REPLACE FUNCTION protect_super_admin() RETURNS trigger AS $$
BEGIN
  IF OLD.role = 'super_admin' AND (
    TG_OP = 'DELETE' OR NEW.role <> 'super_admin' OR NEW.status <> 'active' OR NEW.username <> 'admin'
  ) THEN
    RAISE EXCEPTION 'the unique super administrator is protected';
  END IF;
  RETURN CASE WHEN TG_OP = 'DELETE' THEN OLD ELSE NEW END;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS users_protect_super_admin ON users;
CREATE TRIGGER users_protect_super_admin BEFORE UPDATE OR DELETE ON users
FOR EACH ROW EXECUTE FUNCTION protect_super_admin();

CREATE OR REPLACE FUNCTION audit_logs_immutable() RETURNS trigger AS $$
BEGIN
  RAISE EXCEPTION 'audit logs are append-only';
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_logs_no_mutation ON audit_logs;
CREATE TRIGGER audit_logs_no_mutation BEFORE UPDATE OR DELETE ON audit_logs
FOR EACH ROW EXECUTE FUNCTION audit_logs_immutable();

