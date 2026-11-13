"""Department-scoped People and Commercial access endpoints."""

from __future__ import annotations

from typing import Any

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field
from tinydb import Query

from src.database import get_client_renewals_table, get_people_records_table
from src.models.user import Department, User, UserRole
from src.services.access_control import ensure_employee_self_or_people, require_access
from src.services.auth_service import get_current_user

router = APIRouter(tags=["department-access"])
_people_read = require_access(UserRole.USER, Department.PEOPLE)
_people_supervisor = require_access(UserRole.MANAGER, Department.PEOPLE)
_commercial_read = require_access(UserRole.USER, Department.COMMERCIAL)


class HRRecordCreate(BaseModel):
    user_id: str
    country: str | None = None
    contract: str | None = None
    absences: list[dict[str, Any]] = Field(default_factory=list)
    holidays: list[dict[str, Any]] = Field(default_factory=list)
    onboarding_progress: dict[str, Any] = Field(default_factory=dict)


class RenewalCreate(BaseModel):
    client_name: str = Field(min_length=1, max_length=200)
    renewal_date: str
    status: str = Field(min_length=1, max_length=80)


@router.get("/people/records/{user_id}")
def get_people_record(
    user_id: str,
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ensure_employee_self_or_people(current_user, user_id)
    record = get_people_records_table().get(Query().user_id == user_id)
    if record is None:
        raise HTTPException(status_code=404, detail="Registro laboral no encontrado.")
    return {"user_id": str(record["user_id"]), "country": record.get("country"), "contract": record.get("contract"), "absences": record.get("absences", []), "holidays": record.get("holidays", []), "onboarding_progress": record.get("onboarding_progress", {})}


@router.put("/people/records/{user_id}")
def put_people_record(
    user_id: str,
    payload: HRRecordCreate,
    current_user: User = Depends(_people_supervisor),
) -> dict[str, Any]:
    if payload.user_id != user_id:
        raise HTTPException(status_code=422, detail="user_id debe coincidir con la ruta.")
    table = get_people_records_table()
    data = payload.model_dump()
    data["user_id"] = user_id
    existing = table.get(Query().user_id == user_id)
    if existing is None:
        table.insert(data)
    else:
        table.update(data, doc_ids=[existing.doc_id])
    return data


@router.get("/commercial/renewals")
def list_client_renewals(_current_user: User = Depends(_commercial_read)) -> list[dict[str, Any]]:
    return [{key: value for key, value in record.items() if key != "_default"} for record in get_client_renewals_table().all()]


@router.post("/commercial/renewals", status_code=status.HTTP_201_CREATED)
def create_client_renewal(
    payload: RenewalCreate,
    _current_user: User = Depends(require_access(UserRole.MANAGER, Department.COMMERCIAL)),
) -> dict[str, Any]:
    data = payload.model_dump()
    doc_id = get_client_renewals_table().insert(data)
    return {"id": doc_id, **data}


@router.get("/departments")
def current_department(current_user: User = Depends(get_current_user)) -> dict[str, str | None]:
    return {"role": current_user.role.value, "department": current_user.department.value if current_user.department else None}
