from __future__ import annotations

import pytest

from src.services.password_reset_service import _get_secret_key


def test_password_reset_fails_closed_without_secret_key(monkeypatch) -> None:
    monkeypatch.delenv("SECRET_KEY", raising=False)
    with pytest.raises(RuntimeError, match="SECRET_KEY must be configured"):
        _get_secret_key()


def test_password_reset_uses_configured_secret_key(monkeypatch) -> None:
    monkeypatch.setenv("SECRET_KEY", "test-only-password-reset-secret")
    assert _get_secret_key() == "test-only-password-reset-secret"