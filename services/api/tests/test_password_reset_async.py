from __future__ import annotations

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import Mock

import pytest
from celery.exceptions import Retry

from src.services import async_email_service, password_reset_service
from src.tasks import send_password_reset_email


def test_duplicate_idempotency_key_enqueues_once(monkeypatch) -> None:
    user = SimpleNamespace(id=42, email="user@example.test")
    saved: dict[str, object] = {}
    enqueued: list[object] = []

    monkeypatch.setattr(password_reset_service, "_get_reset_expire_minutes", lambda: 30)
    monkeypatch.setattr(password_reset_service, "_get_secret_key", lambda: "unit-test-secret")
    monkeypatch.setattr(password_reset_service, "_get_algorithm", lambda: "HS256")
    monkeypatch.setattr(password_reset_service.jwt, "encode", lambda *_args, **_kwargs: "opaque-token")
    monkeypatch.setattr(password_reset_service, "_store_reset_token", lambda *_args: True)
    monkeypatch.setattr(password_reset_service, "_build_reset_link", lambda _token: "https://example.test/reset?token=opaque-token")
    monkeypatch.setattr(async_email_service, "find_operation_by_key", lambda key: saved.get("existing"))
    monkeypatch.setattr(async_email_service, "get_operation", lambda _operation_id: None)

    def create_operation(key: str) -> tuple[str, bool]:
        if "operation_id" in saved:
            return str(saved["operation_id"]), False
        saved.update(operation_id="operation-1", key=key)
        return "operation-1", True

    monkeypatch.setattr(async_email_service, "create_or_get_operation", create_operation)
    monkeypatch.setattr(async_email_service, "store_secret_payload", lambda op, payload: saved.update(payload=payload))
    from src.tasks import send_password_reset_email

    monkeypatch.setattr(send_password_reset_email, "apply_async", lambda **kwargs: enqueued.append(kwargs))

    first = password_reset_service.issue_password_reset(user, idempotency_key="request-1")
    saved["existing"] = first
    second = password_reset_service.issue_password_reset(user, idempotency_key="request-1")

    assert first == second == "operation-1"
    assert len(enqueued) == 1
    assert enqueued[0]["kwargs"] == {"schema_version": 1, "operation_id": "operation-1"}


def test_worker_skips_already_completed_operation(monkeypatch) -> None:
    completed = Mock(return_value=True)
    claim = Mock()
    monkeypatch.setattr("src.tasks.is_operation_completed", completed)
    monkeypatch.setattr("src.tasks.claim_operation", claim)

    result = send_password_reset_email.run(schema_version=1, operation_id="done-task")

    assert result["status"] == "completed"
    assert result["deduplicated"] is True
    claim.assert_not_called()


def test_worker_retries_with_exponential_countdown(monkeypatch) -> None:
    monkeypatch.setattr("src.tasks.is_operation_completed", lambda _op: False)
    monkeypatch.setattr("src.tasks.claim_operation", lambda _op: True)
    monkeypatch.setattr("src.tasks.load_secret_payload", lambda _op: {
        "schema_version": 1,
        "operation_id": "operation-2",
        "idempotency_key": "key",
        "recipient": "user@example.test",
        "reset_link": "https://example.test/reset?token=secret",
        "expire_minutes": 30,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    monkeypatch.setattr("src.tasks._send_reset_email", Mock(side_effect=RuntimeError("provider down")))
    monkeypatch.setattr("src.tasks.update_operation", Mock())
    retry = Mock(return_value=Retry("retry"))
    monkeypatch.setattr(send_password_reset_email, "retry", retry)

    send_password_reset_email.push_request(retries=1, id="operation-2")
    try:
        with pytest.raises(Retry):
            send_password_reset_email.run(schema_version=1, operation_id="operation-2")
    finally:
        send_password_reset_email.pop_request()

    retry.assert_called_once()
    assert retry.call_args.kwargs["countdown"] == 2


def test_worker_dead_letters_after_retry_limit(monkeypatch) -> None:
    monkeypatch.setattr("src.tasks.is_operation_completed", lambda _op: False)
    monkeypatch.setattr("src.tasks.claim_operation", lambda _op: True)
    monkeypatch.setattr("src.tasks.load_secret_payload", lambda _op: {
        "schema_version": 1,
        "operation_id": "operation-3",
        "idempotency_key": "key",
        "recipient": "user@example.test",
        "reset_link": "https://example.test/reset?token=secret",
        "expire_minutes": 30,
        "requested_at": datetime.now(timezone.utc).isoformat(),
    })
    monkeypatch.setattr("src.tasks._send_reset_email", Mock(side_effect=RuntimeError("provider down")))
    update = Mock()
    dead_letter = Mock()
    monkeypatch.setattr("src.tasks.update_operation", update)
    monkeypatch.setattr("src.tasks.save_dead_letter", dead_letter)

    send_password_reset_email.push_request(retries=3, id="operation-3")
    try:
        with pytest.raises(RuntimeError):
            send_password_reset_email.run(schema_version=1, operation_id="operation-3")
    finally:
        send_password_reset_email.pop_request()

    update.assert_called_once()
    assert update.call_args.kwargs["status"] == "failed"
    dead_letter.assert_called_once_with("operation-3", 4, "Email provider delivery failed")
