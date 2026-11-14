"""Security tests for explicit Microsoft identity linking and federated login."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

from fastapi.testclient import TestClient


def test_unlinked_microsoft_login_is_rejected_without_creating_account(fresh_db, monkeypatch):
    from src.database import get_users_table, get_federated_audit_table
    from src.routes.federated_auth_router import federated_auth_router
    from fastapi import FastAPI
    from src.services.federated_auth_service import create_oauth_transaction
    from src.services.microsoft_oauth_service import build_authorization_url

    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "test-client")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "organizations")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/federated/microsoft/callback")
    before = len(get_users_table())
    transaction = create_oauth_transaction("login")
    assert build_authorization_url(transaction)

    from src.routes import federated_auth_router as federated_router_module

    monkeypatch.setattr(
        federated_router_module,
        "exchange_and_validate_identity",
        lambda _code, _transaction: {
            "provider_user_id": "ms-oid-unknown-999",
            "email": "unknown@external.example",
        },
    )
    app = FastAPI()
    app.include_router(federated_auth_router)
    client = TestClient(app)
    response = client.get(
        "/auth/federated/microsoft/callback",
        params={"code": "mock-code", "state": transaction.state},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "account_not_linked" in response.headers["location"]
    assert len(get_users_table()) == before
    assert not get_federated_audit_table().search(lambda row: row["event"] == "federated_link")
    rejected = get_federated_audit_table().search(lambda row: row["event"] == "federated_login_rejected")
    assert len(rejected) == 1
    assert rejected[0]["provider_user_id"] == "ms-oid-unknown-999"
    assert rejected[0]["user_id"] is None


def test_authenticated_linking_is_unique_and_audited(fresh_db, test_user, monkeypatch):
    from src.database import get_federated_audit_table
    from src.services.federated_auth_service import FederatedAuthError, link_identity
    from src.services.user_service import create_user

    user, _password = test_user
    linked = link_identity(user, "ms-oid-one", "qa@external.example")
    assert linked.provider == "microsoft"
    assert len(get_federated_audit_table().search(lambda row: row["event"] == "federated_link")) == 1
    other = create_user(email="other@trackflow.io", password="Other!Pass2026")
    try:
        import pytest

        with pytest.raises(FederatedAuthError, match="another TrackFlow account"):
            link_identity(other, "ms-oid-one", "qa@external.example")
    finally:
        from src.services.user_service import delete_user

        delete_user(other.id)


def test_unlink_rejects_last_access_method_and_audits_success(fresh_db, test_user):
    import pytest

    from src.database import get_federated_audit_table, get_users_table
    from src.models.user import User
    from src.services.federated_auth_service import FederatedAuthError, link_identity, unlink_identity

    user, _password = test_user
    link_identity(user, "ms-oid-unlink", "qa@external.example")
    # The stored service user normally has a password; simulate a federated-only
    # account to check the API-level invariant directly.
    raw = get_users_table().get(doc_id=user.id)
    get_users_table().update({"hashed_password": ""}, doc_ids=[user.id])
    federated_only = user.model_copy(update={"hashed_password": ""})
    with pytest.raises(FederatedAuthError, match="Add a password"):
        unlink_identity(federated_only, "microsoft")

    get_users_table().update({"hashed_password": user.hashed_password}, doc_ids=[user.id])
    unlink_identity(user, "microsoft")
    assert len(get_federated_audit_table().search(lambda row: row["event"] == "federated_unlink")) == 1


def test_oauth_state_is_single_use_and_redirect_is_fixed(fresh_db, test_user, monkeypatch):
    import pytest

    from src.services.federated_auth_service import (
        FederatedAuthError,
        consume_oauth_transaction,
        create_oauth_transaction,
    )
    from src.services.microsoft_oauth_service import MicrosoftOAuthError, get_redirect_uri

    transaction = create_oauth_transaction("login")
    assert consume_oauth_transaction(transaction.state, "login").state == transaction.state
    with pytest.raises(FederatedAuthError, match="invalid, expired, or already used"):
        consume_oauth_transaction(transaction.state, "login")

    link_transaction = create_oauth_transaction("link", user_id=test_user[0].id)
    with pytest.raises(FederatedAuthError, match="purpose does not match"):
        consume_oauth_transaction(link_transaction.state, "login")
    assert consume_oauth_transaction(link_transaction.state, "link").purpose == "link"

    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://auth.trackflow.example/callback")
    assert get_redirect_uri() == "https://auth.trackflow.example/callback"
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "https://attacker.example/callback")
    # The configured URI is validated syntactically and used verbatim in both
    # authorization and token requests; callback input cannot override it.
    assert get_redirect_uri() == "https://attacker.example/callback"


def test_seed_creates_linked_internal_and_unlinked_b2b_user_idempotently(fresh_db):
    from src.services.federated_auth_service import get_identity, seed_federated_auth_users
    from src.services.user_service import get_user_by_email

    users = seed_federated_auth_users()
    assert len(users) == 2
    miguel = get_user_by_email("miguel.commercial@trackflow.example")
    northwind = get_user_by_email("brand.am@northwind.example")
    assert miguel is not None and miguel.audience == "internal"
    assert northwind is not None and northwind.audience == "b2b_client"
    assert get_identity("microsoft", "ms-oid-miguel-001").user_id == miguel.id
    assert get_identity("microsoft", "ms-oid-northwind-001") is None
    assert len(seed_federated_auth_users()) == 2


def test_federated_only_user_can_set_initial_password(fresh_db):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.database import get_users_table
    from src.routes.auth_router import auth_router
    from src.services.auth_service import create_access_token
    from src.services.user_service import create_user

    user = create_user(email="federated-only@trackflow.example", password="Initial!Password")
    get_users_table().update({"hashed_password": ""}, doc_ids=[user.id])
    app = FastAPI()
    app.include_router(auth_router)
    response = TestClient(app).post(
        "/auth/change-password",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
        json={"current_password": "", "new_password": "New!Password2026"},
    )
    assert response.status_code == 200
    from src.services.user_service import get_user_by_id

    updated = get_user_by_id(user.id)
    assert updated is not None and updated.hashed_password


def test_link_routes_require_authenticated_trackflow_user(fresh_db):
    from src.routes.federated_auth_router import federated_auth_router
    from fastapi import FastAPI

    app = FastAPI()
    app.include_router(federated_auth_router)
    response = TestClient(app).post("/auth/federated/microsoft/link/start")
    assert response.status_code == 401


def test_callback_rejects_redirect_uri_mismatch_without_consuming_state(fresh_db, test_user, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient
    import pytest

    from src.routes.federated_auth_router import federated_auth_router
    from src.services.federated_auth_service import (
        consume_oauth_transaction,
        create_oauth_transaction,
    )

    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/federated/microsoft/callback")
    transaction = create_oauth_transaction("login")
    app = FastAPI()
    app.include_router(federated_auth_router)
    response = TestClient(app).get(
        "/auth/federated/microsoft/callback",
        params={
            "code": "mock-code",
            "state": transaction.state,
            "redirect_uri": "https://attacker.example/callback",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert "redirect_uri_mismatch" in response.headers["location"]
    assert consume_oauth_transaction(transaction.state, "login").state == transaction.state


def test_successful_federated_login_issues_standard_jwt_and_audits(fresh_db, test_user, monkeypatch):
    from fastapi import FastAPI
    from fastapi.testclient import TestClient

    from src.database import get_federated_audit_table
    from src.routes.federated_auth_router import federated_auth_router
    from src.services.auth_service import _get_secret_key, _get_algorithm
    from src.services.federated_auth_service import create_oauth_transaction, link_identity
    from jose import jwt
    from src.routes import federated_auth_router as route_module

    user, _password = test_user
    monkeypatch.setenv("MICROSOFT_CLIENT_ID", "test-client")
    monkeypatch.setenv("MICROSOFT_CLIENT_SECRET", "test-secret")
    monkeypatch.setenv("MICROSOFT_TENANT_ID", "organizations")
    monkeypatch.setenv("OAUTH_REDIRECT_URI", "http://localhost:8000/auth/federated/microsoft/callback")
    link_identity(user, "ms-oid-success-path", "qa@external.example")
    transaction = create_oauth_transaction("login")
    monkeypatch.setattr(
        route_module,
        "exchange_and_validate_identity",
        lambda _code, _transaction: {
            "provider_user_id": "ms-oid-success-path",
            "email": "qa@external.example",
        },
    )
    app = FastAPI()
    app.include_router(federated_auth_router)
    client = TestClient(app)
    callback = client.get(
        "/auth/federated/microsoft/callback",
        params={"code": "mock-code", "state": transaction.state},
        follow_redirects=False,
    )
    assert callback.status_code == 303, callback.headers.get("location")
    code = parse_qs(urlparse(callback.headers["location"]).query)["federated_code"][0]
    exchanged = client.post("/auth/federated/exchange", json={"code": code})
    assert exchanged.status_code == 200
    token = exchanged.json()["access_token"]
    assert jwt.decode(token, _get_secret_key(), algorithms=[_get_algorithm()])["sub"] == str(user.id)
    events = get_federated_audit_table().search(lambda row: row["event"] == "federated_login_success")
    assert len(events) == 1 and events[0]["provider_user_id"] == "ms-oid-success-path"
    from src.services.federated_auth_service import FederatedAuthError, consume_login_code

    with __import__("pytest").raises(FederatedAuthError, match="invalid, expired, or already used"):
        consume_login_code(code)
