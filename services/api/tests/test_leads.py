from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
import pytest

from src.database import get_leads_table
from src.routes.leads_router import leads_router


@pytest.fixture
def clean_leads_db(fresh_db):
    get_leads_table().truncate()
    return fresh_db


def _client() -> TestClient:
    app = FastAPI()
    app.include_router(leads_router)
    return TestClient(app)


def _lead_payload() -> dict:
    return {
        "companyName": "Acme Commerce",
        "contactPerson": "Ana García",
        "corporateEmail": "ana@acme.example",
        "phone": "+1 213 555 0147",
        "website": "https://acme.example",
        "countryOperation": "Estados Unidos",
        "productType": "Moda",
        "monthlyVolume": "101-500",
        "services": ["Almacenaje", "Logística inversa"],
        "other3pl": "No",
        "comments": "Necesitamos ampliar capacidad en temporada alta.",
        "privacyPolicy": True,
    }


def test_public_intake_persists_valid_lead_without_auth(clean_leads_db) -> None:
    response = _client().post("/leads", json=_lead_payload())

    assert response.status_code == 201, response.text
    body = response.json()
    assert body["companyName"] == "Acme Commerce"
    assert body["status"] == "new"
    assert body["id"]
    assert body["createdAt"]
    assert body["updatedAt"]
    assert len(get_leads_table()) == 1


def test_public_intake_rejects_invalid_or_privacy_unchecked_payload(clean_leads_db) -> None:
    payload = _lead_payload()
    payload["privacyPolicy"] = False
    response = _client().post("/leads", json=payload)
    assert response.status_code == 422
    assert len(get_leads_table()) == 0


def test_public_intake_rejects_phone_without_country_code(clean_leads_db) -> None:
    payload = _lead_payload()
    payload["phone"] = "213 555 0147"

    response = _client().post("/leads", json=payload)

    assert response.status_code == 422
    assert len(get_leads_table()) == 0


def test_crm_requires_internal_operator_authentication(clean_leads_db, auth_token) -> None:
    client = _client()
    headers = {"Authorization": f"Bearer {auth_token}"}
    assert client.get("/leads", headers=headers).status_code == 403
    assert client.get("/leads").status_code == 401


def test_manager_can_list_filter_update_delete_leads(clean_leads_db, manager_token) -> None:
    client = _client()
    created = client.post("/leads", json=_lead_payload())
    assert created.status_code == 201, created.text
    lead_id = created.json()["id"]
    headers = {"Authorization": f"Bearer {manager_token}"}

    listed = client.get("/leads?status=new", headers=headers)
    assert listed.status_code == 200
    assert [lead["id"] for lead in listed.json()] == [lead_id]

    status_response = client.patch(
        f"/leads/{lead_id}/status",
        json={"status": "qualified"},
        headers=headers,
    )
    assert status_response.status_code == 200
    assert status_response.json()["status"] == "qualified"
    assert client.get("/leads?status=new", headers=headers).json() == []

    update = _lead_payload()
    update["companyName"] = "Acme Commerce Europe"
    updated = client.put(f"/leads/{lead_id}", json=update, headers=headers)
    assert updated.status_code == 200
    assert updated.json()["companyName"] == "Acme Commerce Europe"
    assert updated.json()["status"] == "qualified"

    deleted = client.delete(f"/leads/{lead_id}", headers=headers)
    assert deleted.status_code == 204
    assert client.get(f"/leads/{lead_id}", headers=headers).status_code == 404