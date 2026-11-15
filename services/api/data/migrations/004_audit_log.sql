-- Append-only audit ledger. Apply with the application role having INSERT/SELECT
-- only; migrations must be run by a separate database owner role.
CREATE TABLE IF NOT EXISTS audit_log (
    id VARCHAR(36) PRIMARY KEY,
    actor_id VARCHAR(160) NOT NULL,
    actor_type VARCHAR(16) NOT NULL CHECK (actor_type IN ('human', 'process')),
    actor_name VARCHAR(254) NOT NULL,
    action VARCHAR(100) NOT NULL,
    resource_type VARCHAR(100) NOT NULL,
    resource_id VARCHAR(200) NOT NULL,
    occurred_at TIMESTAMPTZ NOT NULL,
    source VARCHAR(200) NOT NULL,
    department VARCHAR(100) NOT NULL,
    country VARCHAR(80),
    warehouse_id VARCHAR(100),
    details_json TEXT NOT NULL DEFAULT '{}',
    previous_hash VARCHAR(64) NOT NULL,
    event_hash VARCHAR(64) NOT NULL UNIQUE
);
CREATE INDEX IF NOT EXISTS ix_audit_log_actor_id ON audit_log (actor_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_action ON audit_log (action);
CREATE INDEX IF NOT EXISTS ix_audit_log_resource_type ON audit_log (resource_type);
CREATE INDEX IF NOT EXISTS ix_audit_log_resource_id ON audit_log (resource_id);
CREATE INDEX IF NOT EXISTS ix_audit_log_occurred_at ON audit_log (occurred_at);
CREATE INDEX IF NOT EXISTS ix_audit_log_department ON audit_log (department);

-- PostgreSQL trigger rejects mutation even if an accidental application route is
-- added. The runtime role should additionally have no UPDATE/DELETE/TRUNCATE rights.
CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only; % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;
DROP TRIGGER IF EXISTS audit_log_no_mutation ON audit_log;
CREATE TRIGGER audit_log_no_mutation
    BEFORE UPDATE OR DELETE ON audit_log
    FOR EACH ROW EXECUTE FUNCTION reject_audit_log_mutation();
