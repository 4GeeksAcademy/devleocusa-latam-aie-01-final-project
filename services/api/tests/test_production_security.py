from __future__ import annotations

import pytest

from src.services.auth_service import _get_secret_key, validate_production_security


def test_production_security_rejects_missing_tls_redis(monkeypatch, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("a-production-secret-value", encoding="utf-8")
    monkeypatch.setenv("TRACKFLOW_ENV", "production")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret))
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "test-only-client-secret")
    monkeypatch.setenv("REDIS_URL", "redis://redis:6379/0")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "https://app.example.com")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://auth.example.com/realms/trackflow")

    with pytest.raises(RuntimeError, match="TLS-protected Redis"):
        validate_production_security()


def test_production_security_rejects_http_public_origin(monkeypatch, tmp_path):
    secret = tmp_path / "secret"
    secret.write_text("a-production-secret-value", encoding="utf-8")
    monkeypatch.setenv("TRACKFLOW_ENV", "production")
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret))
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "test-only-client-secret")
    monkeypatch.setenv("REDIS_URL", "rediss://redis.example.com:6380/0")
    monkeypatch.setenv("CORS_ALLOWED_ORIGINS", "http://app.example.com")
    monkeypatch.setenv("MCP_PUBLIC_URL", "https://mcp.example.com")
    monkeypatch.setenv("OAUTH_ISSUER_URL", "https://auth.example.com/realms/trackflow")

    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        validate_production_security()


def test_signing_secret_can_be_mounted_as_secret_file(monkeypatch, tmp_path):
    secret = tmp_path / "api-secret"
    secret.write_text("mounted-secret", encoding="utf-8")
    monkeypatch.delenv("SECRET_KEY", raising=False)
    monkeypatch.setenv("SECRET_KEY_FILE", str(secret))

    assert _get_secret_key() == "mounted-secret"