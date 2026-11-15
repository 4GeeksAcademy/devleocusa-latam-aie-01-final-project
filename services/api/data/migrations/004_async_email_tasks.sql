-- Durable status and idempotency ledger for asynchronous password-reset email.
-- Apply through the normal database migration process before deploying API/worker.
CREATE TABLE IF NOT EXISTS async_email_tasks (
    operation_id VARCHAR(36) PRIMARY KEY,
    idempotency_key VARCHAR(64) NOT NULL UNIQUE,
    status VARCHAR(16) NOT NULL CHECK (status IN ('pending', 'processing', 'completed', 'failed')),
    retry_count INTEGER NOT NULL DEFAULT 0 CHECK (retry_count >= 0),
    created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
    completed_at TIMESTAMPTZ NULL,
    last_error VARCHAR(500) NULL
);
CREATE INDEX IF NOT EXISTS ix_async_email_tasks_status ON async_email_tasks (status);
