"""HTTP-level authorization tests for independent role and department policies."""

from __future__ import annotations

import pytest
from fastapi.testclient import TestClient
from src.models.user import Department, UserRole


@pytest.fixture
def access_client(monkeypatch):
    from src.fastapi_server import app
    from src.services import auth_service
    from src.services.user_service import create_user
    from src.models.user import Department, UserRole
    from src.database import get_users_table, get_profiles_table
    from tinydb import Query

    # Avoid lifespan integrations (Redis, Qdrant, external model providers) in API policy tests.
    client = TestClient(app, raise_server_exceptions=False)
    created = []

    def make_user(email: str, role: UserRole, department: Department | None = None):
        user = create_user(
            email=email,
            password="Role!Test2025",
            role=role,
            department=department,
            name="Authorization test",
        )
        created.append(user)
        return user, auth_service.create_access_token(user.id)

    yield client, make_user

    for user in created:
        get_profiles_table().remove(Query().user_id == user.id)
        get_users_table().remove(doc_ids=[user.id])


def test_commercial_renewals_deny_other_department_and_employee_write(access_client):
    client, make_user = access_client
    warehouse_supervisor, token = make_user("warehouse.manager@access.test", UserRole.MANAGER, Department.WAREHOUSE_OPERATIONS)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/commercial/renewals", headers=headers).status_code == 403
    assert client.post(
        "/commercial/renewals",
        headers=headers,
        json={"client_name": "Acme", "renewal_date": "2026-12-01", "status": "pending"},
    ).status_code == 403
    assert warehouse_supervisor.department == Department.WAREHOUSE_OPERATIONS


def test_people_records_allow_own_read_only_and_reject_other_employee(access_client):
    client, make_user = access_client
    employee, token = make_user("employee.people@access.test", UserRole.USER, Department.WAREHOUSE_OPERATIONS)
    colleague, _ = make_user("colleague.people@access.test", UserRole.USER, Department.WAREHOUSE_OPERATIONS)
    from src.database import get_people_records_table
    get_people_records_table().insert({"user_id": str(employee.id), "contract": "indefinite"})
    get_people_records_table().insert({"user_id": str(colleague.id), "contract": "temporary"})
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get(f"/people/records/{employee.id}", headers=headers).status_code == 200
    assert client.get(f"/people/records/{colleague.id}", headers=headers).status_code == 403


def test_admin_has_global_access_and_can_list_departments(access_client):
    client, make_user = access_client
    _admin, token = make_user("admin.access@access.test", UserRole.ADMIN, None)
    headers = {"Authorization": f"Bearer {token}"}

    assert client.get("/commercial/renewals", headers=headers).status_code == 200
    response = client.get("/users/departments", headers=headers)
    assert response.status_code == 200
    assert len(response.json()) == 8


def test_role_and_department_are_returned_independently(access_client):
    client, make_user = access_client
    _supervisor, token = make_user("warehouse.access@access.test", UserRole.MANAGER, Department.WAREHOUSE_OPERATIONS)

    response = client.get("/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 200
    assert response.json()["role"] == "manager"
    assert response.json()["department"] == Department.WAREHOUSE_OPERATIONS.value


def test_service_role_is_not_a_human_supervisor(access_client):
    client, make_user = access_client
    _service, token = make_user("service.access@access.test", UserRole.SERVICE, Department.TECHNOLOGY)
    response = client.get("/telemetry/report", headers={"Authorization": f"Bearer {token}"})
    assert response.status_code == 403
