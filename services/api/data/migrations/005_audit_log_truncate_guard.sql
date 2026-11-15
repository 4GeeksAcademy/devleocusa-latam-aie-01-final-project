-- Prevent table-wide truncation of the append-only ledger. Apply with the DB owner.
-- The application runtime role must not own audit_log; otherwise it can alter
-- this trigger or its function despite these controls.
CREATE OR REPLACE FUNCTION reject_audit_log_mutation() RETURNS trigger AS $$
BEGIN
    RAISE EXCEPTION 'audit_log is append-only; % is forbidden', TG_OP;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS audit_log_no_truncate ON audit_log;
CREATE TRIGGER audit_log_no_truncate
    BEFORE TRUNCATE ON audit_log
    FOR EACH STATEMENT EXECUTE FUNCTION reject_audit_log_mutation();

REVOKE UPDATE, DELETE, TRUNCATE, REFERENCES, TRIGGER ON audit_log FROM PUBLIC;
