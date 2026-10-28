from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.database import get_incidents_table, get_users_table
from src.routes.incidents_fastapi_router import incidents_fastapi_router
from src.services.auth_service import create_access_token
from src.services.user_service import create_user


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(incidents_fastapi_router)
    return TestClient(app)


def test_customer_user_cannot_read_or_mutate_global_incidents(auth_token) -> None:
    client = _client()
    headers = {"Authorization": f"Bearer {auth_token}"}

    responses = [
        client.get("/api/incidents", headers=headers),
        client.get("/api/incidents/summary", headers=headers),
        client.get("/api/incidents/not-owned-id", headers=headers),
        client.post("/api/incidents", json={}, headers=headers),
        client.patch("/api/incidents/not-owned-id/status", json={}, headers=headers),
    ]

    assert [response.status_code for response in responses] == [403] * len(responses)


def test_internal_manager_can_read_incident_collection(manager_token) -> None:
    response = _client().get(
        "/api/incidents",
        headers={"Authorization": f"Bearer {manager_token}"},
    )

    assert response.status_code == 200
    assert isinstance(response.json(), list)


def test_mcp_service_role_can_use_scoped_incident_api(service_token) -> None:
    client = _client()
    headers = {"Authorization": f"Bearer {service_token}"}
    response = client.get(
        "/api/incidents",
        headers=headers,
    )
    assert response.status_code == 200

    # The dedicated service identity supports MCP status transitions, but
    # cannot create incidents or use the bulk CSV analysis endpoint.
    create_response = client.post("/api/incidents", json={}, headers=headers)
    analyze_response = client.post("/api/incidents/analyze", headers=headers)
    assert create_response.status_code == 403
    assert analyze_response.status_code == 403


def test_incidents_are_isolated_between_server_assigned_tenants() -> None:
    tenant_a = create_user(
        email="operator-a@tenant-test.invalid",
        password="TenantA!2025",
        role="manager",
        tenant_id="tenant-a",
    )
    tenant_b = create_user(
        email="operator-b@tenant-test.invalid",
        password="TenantB!2025",
        role="manager",
        tenant_id="tenant-b",
    )
    client = _client()
    headers_a = {"Authorization": f"Bearer {create_access_token(tenant_a.id)}"}
    headers_b = {"Authorization": f"Bearer {create_access_token(tenant_b.id)}"}
    payload = {
        "title": "Incidente tenant A",
        "description": "Solo debe ser visible para tenant A.",
        "category": "CX",
        "status": "open",
        "origin": "customer",
        "branch": "Central",
        # Never use client-supplied ownership; the authenticated principal wins.
        "tenant_id": "tenant-b",
    }

    try:
        created = client.post("/api/incidents", json=payload, headers=headers_a)
        assert created.status_code == 201, created.text
        incident_id = created.json()["id"]
        assert created.json()["tenant_id"] == "tenant-a"

        assert client.get("/api/incidents", headers=headers_b).json() == []
        assert client.get(f"/api/incidents/{incident_id}", headers=headers_b).status_code == 404
        assert client.patch(
            f"/api/incidents/{incident_id}/status",
            json={"status": "in_progress"},
            headers=headers_b,
        ).status_code == 404
        assert client.get("/api/incidents/summary", headers=headers_b).json()["total"] == 0

        visible_to_a = client.get(f"/api/incidents/{incident_id}", headers=headers_a)
        assert visible_to_a.status_code == 200
        assert visible_to_a.json()["tenant_id"] == "tenant-a"
    finally:
        incidents = get_incidents_table()
        from tinydb import Query
        incidents.remove(Query().tenant_id == "tenant-a")
        users = get_users_table()
        users.remove(doc_ids=[tenant_a.id, tenant_b.id])


def test_unassigned_operator_fails_closed_on_tenant_incident_api(manager_user) -> None:
    # Ordinary manager fixture is provisioned for the shared test tenant;
    # clear the server-side assignment to model a legacy/unprovisioned account.
    user = manager_user[0]
    get_users_table().update({"tenant_id": None}, doc_ids=[user.id])
    token = create_access_token(user.id)
    response = _client().get(
        "/api/incidents",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert response.status_code == 403
