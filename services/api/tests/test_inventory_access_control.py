"""Regression checks for authentication and role gates on inventory routes."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from sqlalchemy.pool import StaticPool
from sqlmodel import Session, SQLModel, create_engine, select

from src.database import get_sql_session
from src.models.models import PendingSKUExit, SKU, SKUEntry, SKUExit
from src.models.user import Department, User, UserRole
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


def test_warehouse_employee_creates_pending_outbound_request():
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

    regular_user = User(
        id="regular-user",
        email="user@example.com",
        hashed_password="x",
        role=UserRole.USER,
        department=Department.WAREHOUSE_OPERATIONS,
    )
    app = FastAPI()
    app.include_router(inventory_router)

    def session_dependency():
        with Session(engine) as session:
            yield session

    app.dependency_overrides[get_sql_session] = session_dependency
    app.dependency_overrides[get_current_user] = lambda: regular_user
    client = TestClient(app)

    response = client.post("/inventory/orders/outbound", json={"sku_id": "sku-1", "quantity": 3})
    assert response.status_code == 202
    request_id = response.json()["request_id"]
    assert response.json()["status"] == "pending"

    excessive_exit = client.post(
        "/inventory/orders/outbound", json={"sku_id": "sku-1", "quantity": 6}
    )
    assert excessive_exit.status_code == 400
    with Session(engine) as session:
        stored_request = session.get(PendingSKUExit, request_id)
        assert stored_request is not None
        assert stored_request.requester_uuid == "regular-user"
        assert stored_request.quantity == 3
        assert session.exec(select(SKUExit)).all() == []
