"""Durable idempotency and lifecycle helpers for asynchronous email tasks."""

from __future__ import annotations

import hashlib
import hmac
import base64
import json
import logging
from datetime import datetime, timedelta, timezone
from uuid import uuid4

from sqlalchemy import text
from cryptography.fernet import Fernet
from sqlalchemy.exc import IntegrityError

from src.database import get_engine

logger = logging.getLogger(__name__)


def _payload_cipher() -> Fernet:
    """Build an encryption cipher from the configured application secret."""
    from src.services.password_reset_service import _get_secret_key

    key = hashlib.sha256(_get_secret_key().encode("utf-8")).digest()
    return Fernet(base64.urlsafe_b64encode(key))


def store_secret_payload(operation_id: str, payload: dict[str, object]) -> None:
    """Encrypt and store the sensitive serialized task contract."""
    encrypted = _payload_cipher().encrypt(json.dumps(payload, separators=(",", ":")).encode())
    query = text("UPDATE async_email_tasks SET secret_payload = :payload WHERE operation_id = :operation_id")
    with get_engine().begin() as conn:
        result = conn.execute(query, {"operation_id": operation_id, "payload": encrypted.decode("ascii")})
        if result.rowcount != 1:
            raise LookupError("Asynchronous email task operation was not found")


def load_secret_payload(operation_id: str) -> dict[str, object]:
    """Decrypt and validate the stored JSON object shape."""
    query = text("SELECT secret_payload FROM async_email_tasks WHERE operation_id = :operation_id")
    with get_engine().connect() as conn:
        encrypted = conn.execute(query, {"operation_id": operation_id}).scalar_one_or_none()
    if not encrypted:
        raise LookupError("Asynchronous email task payload is unavailable")
    payload = _payload_cipher().decrypt(str(encrypted).encode("ascii"))
    result = json.loads(payload)
    if not isinstance(result, dict):
        raise ValueError("Invalid asynchronous email task payload")
    return result


def make_password_reset_idempotency_key(user_id: object, token_hash: str) -> str:
    """Derive an opaque key stable for duplicate dispatch of the same token."""
    from src.services.password_reset_service import _get_secret_key

    material = f"password_reset_email:v1:{user_id}:{token_hash}".encode("utf-8")
    return hmac.new(_get_secret_key().encode("utf-8"), material, hashlib.sha256).hexdigest()


def create_or_get_operation(idempotency_key: str) -> tuple[str, bool]:
    """Atomically create a pending operation or return its prior operation ID."""
    operation_id = str(uuid4())
    insert = text(
        """INSERT INTO async_email_tasks
           (operation_id, idempotency_key, status, retry_count, created_at, updated_at)
           VALUES (:operation_id, :key, 'pending', 0, now(), now())
           ON CONFLICT (idempotency_key) DO NOTHING
           RETURNING operation_id"""
    )
    select = text("SELECT operation_id FROM async_email_tasks WHERE idempotency_key = :key")
    try:
        with get_engine().begin() as conn:
            inserted = conn.execute(insert, {"operation_id": operation_id, "key": idempotency_key}).scalar_one_or_none()
            if inserted:
                return str(inserted), True
            existing = conn.execute(select, {"key": idempotency_key}).scalar_one()
            return str(existing), False
    except IntegrityError:
        # Defensive fallback for databases/drivers without ON CONFLICT support.
        with get_engine().connect() as conn:
            existing = conn.execute(select, {"key": idempotency_key}).scalar_one_or_none()
        if existing:
            return str(existing), False
        raise


def find_operation_by_key(idempotency_key: str) -> str | None:
    """Return the operation associated with a durable idempotency key."""
    query = text("SELECT operation_id FROM async_email_tasks WHERE idempotency_key = :key")
    with get_engine().connect() as conn:
        result = conn.execute(query, {"key": idempotency_key}).scalar_one_or_none()
    return str(result) if result else None


def get_operation(operation_id: str) -> dict[str, object] | None:
    """Return public lifecycle metadata for one asynchronous operation."""
    query = text(
        """SELECT operation_id, status, retry_count, created_at, updated_at,
                  completed_at, last_error
           FROM async_email_tasks WHERE operation_id = :operation_id"""
    )
    with get_engine().connect() as conn:
        row = conn.execute(query, {"operation_id": operation_id}).mappings().first()
    return dict(row) if row else None


def update_operation(
    operation_id: str,
    *,
    status: str,
    retry_count: int | None = None,
    error_message: str | None = None,
    completed: bool = False,
) -> None:
    if status not in {"pending", "processing", "completed", "failed"}:
        raise ValueError("Invalid asynchronous email task status")
    query = text(
        """UPDATE async_email_tasks
           SET status = :status,
               retry_count = COALESCE(:retry_count, retry_count),
               updated_at = :updated_at,
               completed_at = CASE WHEN :completed THEN :updated_at ELSE completed_at END,
               processing_started_at = CASE WHEN :status = 'processing'
                                            THEN processing_started_at
                                            ELSE NULL END,
               last_error = :last_error
           WHERE operation_id = :operation_id"""
    )
    safe_error = (error_message or "")[:500] or None
    with get_engine().begin() as conn:
        result = conn.execute(
            query,
            {
                "operation_id": operation_id,
                "status": status,
                "retry_count": retry_count,
                "updated_at": datetime.now(timezone.utc),
                "completed": completed,
                "last_error": safe_error,
            },
        )
        if result.rowcount != 1:
            raise LookupError("Asynchronous email task operation was not found")


def is_operation_completed(operation_id: str) -> bool:
    """Check whether an operation has already completed successfully."""
    query = text("SELECT status FROM async_email_tasks WHERE operation_id = :operation_id")
    with get_engine().connect() as conn:
        result = conn.execute(query, {"operation_id": operation_id}).scalar_one_or_none()
    return result == "completed"


def claim_operation(operation_id: str) -> bool:
    """Claim a pending task exactly once before contacting the provider."""
    query = text(
        """UPDATE async_email_tasks
           SET status = 'processing', updated_at = :updated_at,
               processing_started_at = :updated_at
           WHERE operation_id = :operation_id
             AND (status = 'pending'
                  OR (status = 'processing'
                      AND processing_started_at < :stale_before))"""
    )
    now = datetime.now(timezone.utc)
    with get_engine().begin() as conn:
        result = conn.execute(
            query,
            {
                "operation_id": operation_id,
                "updated_at": now,
                "stale_before": now - timedelta(minutes=45),
            },
        )
    return result.rowcount == 1


def save_dead_letter(operation_id: str, attempt: int, safe_error: str) -> None:
    """Persist exhausted work; never include provider payload or credentials."""
    query = text(
        """INSERT INTO dead_letter_queue (task_id, attempt, error_message, "timestamp")
           VALUES (:task_id, :attempt, :error_message, now())"""
    )
    with get_engine().begin() as conn:
        conn.execute(query, {
            "task_id": operation_id,
            "attempt": attempt,
            "error_message": safe_error[:500],
        })
    logger.error("async_email_dead_lettered operation_id=%s attempt=%d", operation_id, attempt)
