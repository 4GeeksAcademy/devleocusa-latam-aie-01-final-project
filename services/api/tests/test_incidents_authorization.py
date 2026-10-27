from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from src.routes.incidents_fastapi_router import incidents_fastapi_router


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
