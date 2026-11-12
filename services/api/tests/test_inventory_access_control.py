"""Regression checks for authentication and role gates on inventory routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database import get_sql_session
from src.models.models import PendingSKUExit, SKU, SKUEntry, SKUExit
from src.models.user import User, UserRole
from src.routes.inventory import inventory_router
from src.services.auth_service import create_access_token, get_current_user


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
    assert client.post(
        "/inventory/orders/outbound",
        json={"sku_id": "example", "quantity": 1},
    ).status_code == 401


def test_inventory_write_rejects_regular_user(test_user):
    user, _ = test_user
    client = TestClient(_app())
    response = client.post(
        "/inventory/products",
        headers={"Authorization": f"Bearer {create_access_token(user.id)}"},
        json={"name": "Test SKU", "sku_code": "T-1", "warehouse": "Zaragoza"},
    )
    assert response.status_code == 403


def test_regular_user_records_outbound_dispatch_immediately():
    engine = create_engine(
        "sqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    for model in (SKU.__table__, SKUEntry.__table__, SKUExit.__table__, PendingSKUExit.__table__):
        model.create(engine)
    with Session(engine) as session:
        sku = SKU(id="sku-1", name="Test", sku_code="T-1", warehouse="Zaragoza")
        session.add(sku)
        session.add(SKUEntry(sku_id="sku-1", quantity=5, user_uuid="seed"))
        session.commit()

    regular_user = User(id="regular-user", email="user@example.com", hashed_password="x", role=UserRole.USER)
    app = FastAPI()
    app.include_router(inventory_router)

    def session_dependency():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_sql_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: regular_user
    client = TestClient(app)

    response = client.post("/inventory/orders/outbound", json={"sku_id": "sku-1", "quantity": 3})
    assert response.status_code == 201
    exit_id = response.json()["id"]
    assert response.json()["quantity"] == 3

    excessive_exit = client.post(
        "/inventory/orders/outbound", json={"sku_id": "sku-1", "quantity": 3}
    )
    assert excessive_exit.status_code == 400
    products = client.get("/inventory/products")
    assert products.status_code == 200
    assert products.json()[0]["current_stock"] == 2
    assert products.json()[0]["available_stock"] == 2
    with Session(engine) as session:
        stored_exit = session.get(SKUExit, exit_id)
        assert stored_exit is not None
        assert stored_exit.user_uuid == "regular-user"
        assert stored_exit.quantity == 3
        assert session.get(SKUEntry, 1) is None  # entries remain immutable
        assert len(session.exec(select(SKUExit)).all()) == 1
