"""Report generation endpoints — async dispatch via Celery + polling.

Two endpoints:
  1. ``POST /reports/generate`` — dispatches report generation to the
     Celery broker and immediately returns ``202 Accepted`` with the
     ``task_id`` for client-side polling.
  2. ``GET  /tasks/{task_id}`` — queries the Celery result backend
     (Redis) and returns the current state of the task.

Pattern: fire-and-forget + polling.  The heavy PDF rendering happens
in a Celery worker; the FastAPI process stays responsive.
"""

from __future__ import annotations

from enum import Enum
from typing import Any
from uuid import uuid4

from celery.result import AsyncResult
from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel, Field

from src.celery_app import app as celery_app
from src.tasks import generate_report

# ── Router ──────────────────────────────────────────────────────────────

router = APIRouter(tags=["reports"])


# ── Pydantic schemas (strict typing) ───────────────────────────────────


class ReportType(str, Enum):
    """Allowed report types — mirrors ``_REPORT_LABELS`` in ``src.tasks``."""

    EXECUTIVE_WEEKLY = "executive_weekly"
    CLIENT_PDF = "client_pdf"


class TaskState(str, Enum):
    """Celery task states we expose to the client.

    Mapped 1-to-1 from ``AsyncResult.state``.  Any unknown state from
    Celery is normalised to ``PENDING``.
    """

    PENDING = "PENDING"
    STARTED = "STARTED"
    SUCCESS = "SUCCESS"
    FAILURE = "FAILURE"


# ── Request / Response models ──────────────────────────────────────────


class ReportGenerateRequest(BaseModel):
    """Payload accepted by ``POST /reports/generate``."""

    report_type: ReportType = Field(
        ...,
        description="Tipo de informe a generar.",
    )
    report_id: str | None = Field(
        default=None,
        description=(
            "ID del informe. Si se omite se genera uno automáticamente (UUID)."
        ),
        max_length=128,
    )
    client_id: str | None = Field(
        default=None,
        description=(
            "ID del cliente — obligatorio cuando report_type == 'client_pdf'."
        ),
        max_length=128,
    )


class ReportAcceptedResponse(BaseModel):
    """Returned by ``POST /reports/generate`` (HTTP 202)."""

    task_id: str = Field(
        ...,
        description="ID de la tarea Celery encolada.",
    )
    status: TaskState = Field(
        default=TaskState.PENDING,
        description="Estado inicial de la tarea.",
    )
    message: str = Field(
        default="Reporte encolado para generación asíncrona.",
        description="Mensaje informativo para el cliente.",
    )


class TaskStatusResponse(BaseModel):
    """Returned by ``GET /tasks/{task_id}`` — polling endpoint."""

    task_id: str = Field(
        ...,
        description="ID de la tarea Celery.",
    )
    status: TaskState = Field(
        ...,
        description="Estado actual de la tarea.",
    )
    result: Any = Field(
        default=None,
        description=(
            "Resultado de la tarea cuando status == SUCCESS. "
            "Mensaje de error cuando status == FAILURE. "
            "``None`` en otros estados."
        ),
    )


# ── Helpers ─────────────────────────────────────────────────────────────

# Celery states we map 1-to-1; anything else falls back to PENDING.
_CELERY_STATE_MAP: dict[str, TaskState] = {
    "PENDING": TaskState.PENDING,
    "STARTED": TaskState.STARTED,
    "SUCCESS": TaskState.SUCCESS,
    "FAILURE": TaskState.FAILURE,
}


def _normalise_state(raw: str) -> TaskState:
    """Map a Celery ``AsyncResult.state`` to our ``TaskState`` enum."""
    return _CELERY_STATE_MAP.get(raw, TaskState.PENDING)


# ── Endpoints ───────────────────────────────────────────────────────────


@router.post(
    "/reports/generate",
    response_model=ReportAcceptedResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generar informe de forma asíncrona",
    description=(
        "Encola un trabajo de generación de informe en Celery/Redis y "
        "retorna inmediatamente el ``task_id`` para consultas de estado "
        "vía ``GET /tasks/{task_id}``."
    ),
)
async def dispatch_report_generation(body: ReportGenerateRequest):
    """Dispatch report generation to Celery and return 202 Accepted."""
    report_id = body.report_id or str(uuid4())
    client_id = body.client_id

    # Validate: client_id is mandatory for client PDF reports.
    if body.report_type == ReportType.CLIENT_PDF and not client_id:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=(
                "El campo 'client_id' es obligatorio cuando "
                "report_type es 'client_pdf'."
            ),
        )

    # Fire-and-forget: enqueue the task, do NOT wait for completion.
    result = generate_report.delay(
        body.report_type.value,
        report_id,
        client_id,
    )

    return ReportAcceptedResponse(
        task_id=result.id,
        status=TaskState.PENDING,
    )


@router.get(
    "/tasks/{task_id}",
    response_model=TaskStatusResponse,
    summary="Consultar estado de una tarea",
    description=(
        "Consulta el result backend (Redis) para obtener el estado "
        "actual de una tarea Celery.  Usar para polling desde el frontend."
    ),
)
async def get_task_status(task_id: str):
    """Return the current state of a Celery task by its ID."""
    async_result = AsyncResult(task_id, app=celery_app)

    task_state = _normalise_state(async_result.state)

    # Build the result payload depending on the current state.
    result_payload: Any = None
    if task_state == TaskState.SUCCESS:
        result_payload = async_result.result
    elif task_state == TaskState.FAILURE:
        # Return the exception message, not the raw exception object.
        result_payload = str(async_result.result)

    return TaskStatusResponse(
        task_id=task_id,
        status=task_state,
        result=result_payload,
    )
