"""FastAPI incidents routes protected with JWT authentication."""

from __future__ import annotations

from pydantic import BaseModel, Field, ValidationError

from fastapi import APIRouter, Depends, File, HTTPException, UploadFile, status

from src.cache import TTLCache
from src.models.incident import (
    Incident,
    IncidentBranch,
    IncidentCategory,
    IncidentListResponse,
    IncidentOrigin,
    IncidentResponse,
    IncidentStatus,
    IncidentStatusResponse,
)
from src.models.user import User
from src.services.access_control import (
    require_internal_operator,
    require_service_or_operator,
)
from src.services.incidents_analysis_service import analyze_incidents_csv
from src.services.incidents_service import (
    can_transition_status,
    create_incident,
    get_incident_by_id,
    incidents_summary,
    list_incidents,
    update_incident_status,
)

incidents_fastapi_router = APIRouter(tags=["incidents-legacy"])

# ── In-memory TTL cache for aggregated summaries ────────────────────────
# Data changes infrequently but is read constantly (dashboard / KPIs).
_summary_cache = TTLCache(ttl_seconds=30)


def _require_tenant(user: User) -> str:
    """Return the server-provisioned tenant, rejecting unassigned identities."""
    if not user.tenant_id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Tenant membership is required.")
    return user.tenant_id

ACCEPTED_MIME_TYPES = {
    "text/csv",
    "application/csv",
    "application/vnd.ms-excel",
    "text/plain",
}


def _is_csv_upload(uploaded_file: UploadFile) -> bool:
    filename = (uploaded_file.filename or "").lower()
    has_csv_extension = filename.endswith(".csv")
    has_csv_mime_type = (uploaded_file.content_type or "") in ACCEPTED_MIME_TYPES
    return has_csv_extension and has_csv_mime_type


class IncidentCreateRequest(BaseModel):
    """Payload used to create incidents."""

    title: str = Field(min_length=1, max_length=160)
    description: str = Field(min_length=1)
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch


class IncidentStatusPatchRequest(BaseModel):
    """Payload used to update incident status."""

    status: IncidentStatus


def _structured_validation_error(error: ValidationError) -> list[dict[str, str]]:
    details: list[dict[str, str]] = []

    for issue in error.errors():
        field_name = str(issue.get("loc", ["field"])[-1])
        issue_type = str(issue.get("type", ""))
        issue_value = issue.get("input")

        if issue_type == "missing":
            message = f"El campo '{field_name}' es obligatorio."
        elif issue_type.startswith("string_too_short"):
            message = f"El campo '{field_name}' no puede estar vacio."
        elif issue_type.startswith("enum"):
            message = (
                f"El campo '{field_name}' tiene un valor invalido: "
                f"'{issue_value}'."
            )
        else:
            message = f"El campo '{field_name}' no es valido."

        details.append(
            {
                "field": field_name,
                "message": message,
            }
        )

    return details


def _raise_bad_request_with_details(details: list[dict[str, str]]) -> None:
    raise HTTPException(
        status_code=status.HTTP_400_BAD_REQUEST,
        detail={
            "error": "Error de validacion en la solicitud.",
            "details": details,
        },
    )


@incidents_fastapi_router.post("/api/incidents", response_model=IncidentResponse, status_code=status.HTTP_201_CREATED)
def create_incident_route(
    payload: dict,
    current_user: User = Depends(require_internal_operator),
) -> IncidentResponse:
    try:
        request_body = IncidentCreateRequest.model_validate(payload)
    except ValidationError as error:
        _raise_bad_request_with_details(_structured_validation_error(error))

    tenant_id = _require_tenant(current_user)
    incident = create_incident(request_body.model_dump(mode="python"), tenant_id=tenant_id)

    # Invalidate summary cache — a new incident changes all aggregations
    _summary_cache.invalidate(f"summary:{tenant_id}")

    return IncidentResponse.model_validate(incident.model_dump())


@incidents_fastapi_router.get("/api/incidents", response_model=list[IncidentListResponse])
def list_incidents_route(
    status: IncidentStatus | None = None,
    origin: IncidentOrigin | None = None,
    branch: IncidentBranch | None = None,
    category: IncidentCategory | None = None,
    current_user: User = Depends(require_service_or_operator),
) -> list[IncidentListResponse]:
    tenant_id = _require_tenant(current_user)
    incidents = list_incidents(tenant_id=tenant_id, status=status, origin=origin, branch=branch, category=category)
    return [IncidentListResponse.model_validate(i.model_dump()) for i in incidents]


@incidents_fastapi_router.get("/api/incidents/summary")
def incidents_summary_route(
    current_user: User = Depends(require_service_or_operator),
) -> dict[str, object]:
    tenant_id = _require_tenant(current_user)
    # Try cache first — avoids expensive full-table scan
    cache_key = f"summary:{tenant_id}"
    cached = _summary_cache.get(cache_key)
    if cached is not None:
        return cached  # type: ignore[return-value]

    result = incidents_summary(tenant_id=tenant_id)
    _summary_cache.set(cache_key, result)
    return result


@incidents_fastapi_router.get("/api/incidents/{incident_id}", response_model=IncidentResponse)
def get_incident_by_id_route(
    incident_id: str,
    current_user: User = Depends(require_service_or_operator),
) -> IncidentResponse:
    tenant_id = _require_tenant(current_user)
    incident = get_incident_by_id(incident_id, tenant_id=tenant_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidencia no encontrada.")

    return IncidentResponse.model_validate(incident.model_dump())


@incidents_fastapi_router.patch("/api/incidents/{incident_id}/status", response_model=IncidentStatusResponse)
def patch_incident_status_route(
    incident_id: str,
    payload: dict,
    current_user: User = Depends(require_service_or_operator),
) -> IncidentStatusResponse:
    tenant_id = _require_tenant(current_user)
    incident = get_incident_by_id(incident_id, tenant_id=tenant_id)
    if incident is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidencia no encontrada.")

    try:
        request_body = IncidentStatusPatchRequest.model_validate(payload)
    except ValidationError as error:
        _raise_bad_request_with_details(_structured_validation_error(error))

    if not can_transition_status(incident.status, request_body.status):
        _raise_bad_request_with_details(
            [
                {
                    "field": "status",
                    "message": (
                        f"Transicion de estado no permitida: '{incident.status.value}' "
                        f"-> '{request_body.status.value}'."
                    ),
                }
            ]
        )

    updated = update_incident_status(incident_id, request_body.status, tenant_id=tenant_id)
    if updated is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Incidencia no encontrada.")

    # Invalidate summary cache — status transition affects aggregations
    _summary_cache.invalidate(f"summary:{tenant_id}")

    return IncidentStatusResponse(
        id=updated.id,
        status=updated.status,
        updated_at=updated.updated_at,
    )


@incidents_fastapi_router.post("/api/incidents/analyze")
async def analyze_incidents_route(
    file: UploadFile = File(...),
    _current_user: User = Depends(require_internal_operator),
) -> dict:
    if not _is_csv_upload(file):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Formato invalido: el archivo debe ser un CSV valido (.csv).",
        )

    csv_bytes = await file.read()
    if not csv_bytes:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="El archivo CSV esta vacio.")

    try:
        summary = analyze_incidents_csv(csv_bytes)
    except ValueError as error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"No se pudo procesar el CSV: {error}",
        ) from error

    return {"summary": summary}
