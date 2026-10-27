"""Regression tests for authorization on user-management endpoints."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes.users_router import users_router
from src.services.auth_service import create_access_token


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(users_router)
    return TestClient(app)


def _headers(user) -> dict[str, str]:
    return {"Authorization": f"Bearer {create_access_token(user.id)}"}


def test_non_admin_cannot_list_users(test_user, test_admin_user):
    regular_user, _ = test_user
    response = _client().get("/users", headers=_headers(regular_user))
    assert response.status_code == 403


def test_non_admin_cannot_read_another_user(test_user, test_admin_user):
    regular_user, _ = test_user
    other_user, _ = test_admin_user
    response = _client().get(
        f"/users/{other_user.id}", headers=_headers(regular_user)
    )
    assert response.status_code == 403


def test_non_admin_cannot_escalate_own_role(test_user):
    regular_user, _ = test_user
    response = _client().put(
        f"/users/{regular_user.id}",
        headers=_headers(regular_user),
        json={"role": "admin"},
    )
    assert response.status_code == 403


def test_non_admin_cannot_delete_another_user(test_user, test_admin_user):
    regular_user, _ = test_user
    other_user, _ = test_admin_user
    response = _client().delete(
        f"/users/{other_user.id}", headers=_headers(regular_user)
    )
    assert response.status_code == 403


def test_admin_can_manage_users(test_user, test_admin_user):
    target_user, _ = test_user
    admin_user, _ = test_admin_user
    client = _client()
    headers = _headers(admin_user)

    assert client.get("/users", headers=headers).status_code == 200
    assert client.get(f"/users/{target_user.id}", headers=headers).status_code == 200
    assert client.put(
        f"/users/{target_user.id}",
        headers=headers,
        json={"role": "manager"},
    ).status_code == 200


def test_public_registration_cannot_assign_privileged_role(fresh_db):
    response = _client().post(
        "/users",
        json={
            "email": "self-register@trackflow.io",
            "password": "Str0ng!Pass",
            "role": "admin",
        },
    )
    assert response.status_code == 201
    assert response.json()["user"]["role"] == "user"


def test_self_update_cannot_change_role(test_user):
    regular_user, _ = test_user
    response = _client().put(
        f"/users/{regular_user.id}",
        headers=_headers(regular_user),
        json={"role": "admin", "email": "qa-updated@trackflow.io"},
    )
    assert response.status_code == 403
