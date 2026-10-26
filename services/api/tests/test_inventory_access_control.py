"""Regression checks for authentication and role gates on inventory routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_sql_session
from src.routes.inventory import inventory_router
from src.services.auth_service import create_access_token


def _app() -> FastAPI:
    app = FastAPI()
    app.include_router(inventory_router)

    def fake_session():
        yield None

    app.dependency_overrides[get_sql_session] = fake_session
    return app


def test_inventory_reads_require_authentication():
    client = TestClient(_app())
    assert client.get("/inventory/products").status_code == 401
    assert client.get("/inventory/products/example").status_code == 401
    assert client.get("/inventory/orders").status_code == 401


def test_inventory_write_rejects_regular_user(test_user):
    user, _ = test_user
    client = TestClient(_app())
    response = client.post(
        "/inventory/products",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
        json={"name": "Test SKU", "sku_code": "T-1", "warehouse": "Zaragoza"},
    )
    assert response.status_code == 403
