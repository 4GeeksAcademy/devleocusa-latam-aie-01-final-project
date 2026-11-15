# Asynchronous password-reset email contract

The `password_reset_email.v1` Celery message contains only JSON primitives:

```json
{
  "schema_version": 1,
  "operation_id": "<UUID>",
  "idempotency_key": "<SHA-256 hex digest>",
  "recipient": "<address resolved by the API>",
  "reset_link": "<backend-generated one-time URL>",
  "expire_minutes": 30,
  "requested_at": "<UTC ISO-8601 timestamp>"
}
```

The worker needs the recipient and reset URL to send without reading API request state or the TinyDB user object. The SQL `async_email_tasks` row stores only the opaque operation/idempotency IDs, lifecycle status, retry count and sanitized error metadata; it intentionally does not persist the address or reset token/link. Message bodies and provider responses must not be logged. Redis/Celery transport remains a short-lived secret-bearing boundary; restrict access, use TLS/authentication in production, and use encrypted persistent transport if retaining queued password-reset links across broker restarts is required.

The idempotency key is a server-derived HMAC over the operation type, user ID, and reset-token hash, keyed by `SECRET_KEY`. It is stable for duplicate dispatches of the same token and does not reveal the token. The worker checks the durable completed state before sending. SendGrid does not guarantee idempotent email delivery, so a provider acceptance followed by a lost response can still result in a duplicate on retry; this implementation does not claim exactly-once delivery.

Status values are `pending`, `processing`, `completed`, and `failed`. The existing `dead_letter_queue` table is the dead-letter record for tasks that exhaust retries. Apply migration `services/api/data/migrations/004_async_email_tasks.sql` before starting the updated API and worker.
