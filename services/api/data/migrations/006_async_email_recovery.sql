-- Allow stale worker claims to be reclaimed safely after worker loss.
ALTER TABLE async_email_tasks
    ADD COLUMN IF NOT EXISTS processing_started_at TIMESTAMPTZ NULL;
