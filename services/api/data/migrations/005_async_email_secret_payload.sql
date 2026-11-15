-- Encrypted secret-bearing payload is kept outside the Celery broker arguments.
ALTER TABLE async_email_tasks ADD COLUMN IF NOT EXISTS secret_payload TEXT NULL;
