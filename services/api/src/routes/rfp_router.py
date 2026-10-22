"""RFP intake router — same FastAPI app, NO second HTTP service.

    POST /rfp/upload           PDF → ticket (202 + ticket_id; pipeline en background)
    GET  /rfp/tickets          listado con filtro de estado (polling de la UI)
    GET  /rfp/tickets/{id}     detalle: estado, metadatos, legibilidad, aspectos

The router only triggers (background task) and queries (SQLModel rows).
The graph itself lives in data/pipelines/src/rfp_intake and is invoked via
src.pipeline_adapter.
"""

from __future__ import annotations

import json
import logging
import asyncio
from datetime import datetime
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from sqlmodel import Session

from src.database import get_sql_session
from src.models.rfp import DepartmentSection, RFPFinalDocument, RFPTicket, RFPStatus
from src.models.user import User
from src.services.auth_service import get_current_user
from src.services import rfp_service
from src.services.rfp_event_service import rfp_event_broker

rfp_router = APIRouter(prefix="/rfp", tags=["rfp"])
logger = logging.getLogger(__name__)

_ALLOWED_CONTENT_TYPES = {"application/pdf", "application/x-pdf", "application/octet-stream"}


# ── Response schemas ────────────────────────────────────────────────────


class RFPUploadResponse(BaseModel):
    ticket_id: str = Field(..., description="Identificador del ticket para consultar estado")
    status: str = Field(..., description="Estado inicial: siempre 'analizando'")
    detail: str = Field(..., description="Mensaje operativo para la UI")


class RFPTicketSummary(BaseModel):
    id: str
    status: str
    original_filename: str
    created_at: datetime
    updated_at: datetime
    classification_reason: str | None = None
    error_detail: str | None = None


class RFPDocumentOut(BaseModel):
    title: str | None = None
    issuing_organization: str | None = None
    rfp_reference: str | None = None
    proposal_due_date: str | None = None
    contact_name: str | None = None
    contact_email: str | None = None
    detected_language: str | None = None
    word_count: int | None = None
    flesch_kincaid_grade: float | None = None
    gunning_fog_index: float | None = None
    coleman_liau_index: float | None = None
    estimated_token_cost: int | None = None


class RFPArtifactOut(BaseModel):
    department: str
    contact_name: str | None = None
    contact_role: str | None = None
    status: str
    worker_error: str | None = None
    key_aspects: dict[str, Any] | None = None
    proposal_draft: str | None = None
    evaluation_result: dict[str, Any] | None = None
    iteration_count: int = 0
    department_id: str | None = None
    approval_status: str = "pending"
    approver: str | None = None
    approval_comment: str | None = None
    approved_at: datetime | None = None
    approval_iteration_count: int = 0


class RFPTicketDetail(RFPTicketSummary):
    is_rfp: bool | None = None
    classification_confidence: float | None = None
    markdown_path: str | None = None
    synthesis_summary: str | None = None
    dispatched_at: datetime | None = None
    proposal_completed_at: datetime | None = None
    document: RFPDocumentOut | None = None
    sections: list[RFPArtifactOut] = Field(default_factory=list)
    handoff_payload: dict[str, Any] | None = None
    final_document_available: bool = False


class RFPDecisionIn(BaseModel):
    decision: str = Field(..., description="approve, reject o request_changes")
    comment: str = Field(default="", max_length=4000)


# ── Mappers ─────────────────────────────────────────────────────────────


def _summary(ticket: RFPTicket) -> RFPTicketSummary:
    return RFPTicketSummary(
        id=ticket.id,
        status=ticket.status,
        original_filename=ticket.original_filename,
        created_at=ticket.created_at,
        updated_at=ticket.updated_at,
        classification_reason=ticket.classification_reason,
        error_detail=ticket.error_detail,
    )


def _parse_json(raw: str | None) -> dict[str, Any] | None:
    if not raw:
        return None
    try:
        parsed = json.loads(raw)
        return parsed if isinstance(parsed, dict) else None
    except json.JSONDecodeError:
        return None


def _detail(
    ticket: RFPTicket,
    document: Any,
    sections: list[Any],
) -> RFPTicketDetail:
    document_out: RFPDocumentOut | None = None
    if document is not None:
        document_out = RFPDocumentOut(
            title=document.title,
            issuing_organization=document.issuing_organization,
            rfp_reference=document.rfp_reference,
            proposal_due_date=document.proposal_due_date,
            contact_name=document.contact_name,
            contact_email=document.contact_email,
            detected_language=document.detected_language,
            word_count=document.word_count,
            flesch_kincaid_grade=document.flesch_kincaid_grade,
            gunning_fog_index=document.gunning_fog_index,
            coleman_liau_index=document.coleman_liau_index,
            estimated_token_cost=document.estimated_token_cost,
        )
    sections_out = [
        RFPArtifactOut(
            department=section.department,
            contact_name=section.contact_name,
            contact_role=section.contact_role,
            status=section.status,
            worker_error=section.worker_error,
            key_aspects=_parse_json(section.key_aspects),
            proposal_draft=section.proposal_draft,
            evaluation_result=_parse_json(section.evaluation_result),
            iteration_count=section.iteration_count,
            department_id=section.department_id,
            approval_status=section.approval_status,
            approver=section.approver,
            approval_comment=section.approval_comment,
            approved_at=section.approved_at,
            approval_iteration_count=section.approval_iteration_count,
        )
        for section in sections
    ]
    base = _summary(ticket)
    return RFPTicketDetail(
        **base.model_dump(),
        is_rfp=ticket.is_rfp,
        classification_confidence=ticket.classification_confidence,
        markdown_path=ticket.markdown_path,
        synthesis_summary=ticket.synthesis_summary,
        dispatched_at=ticket.dispatched_at,
        proposal_completed_at=ticket.proposal_completed_at,
        document=document_out,
        sections=sections_out,
        handoff_payload=_parse_json(ticket.handoff_payload),
        final_document_available=ticket.status == RFPStatus.COMPLETED.value,
    )


# ── Endpoints ───────────────────────────────────────────────────────────


@rfp_router.get("/events", summary="Notificaciones en tiempo real de RFP")
async def rfp_events(
    _current_user: User = Depends(get_current_user),
) -> StreamingResponse:
    """Stream classified RFP tickets; clients recover missed items from Supabase."""
    async def event_stream():
        subscriber = await rfp_event_broker.subscribe()
        try:
            while True:
                connection_generation = rfp_event_broker.connection_generation
                if rfp_event_broker.should_reconnect_sse:
                    # The client reconnect path refetches the durable Supabase
                    # ticket list before opening another stream.
                    return
                try:
                    event = await asyncio.wait_for(
                        subscriber.queue.get(), timeout=15
                    )
                except TimeoutError:
                    if rfp_event_broker.connection_generation != connection_generation:
                        return
                    yield ": keep-alive\n\n"
                    continue
                payload = json.dumps(event["data"], ensure_ascii=False, separators=(",", ":"))
                yield f"event: {event['event']}\ndata: {payload}\n\n"
        finally:
            await rfp_event_broker.unsubscribe(subscriber)

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@rfp_router.post(
    "/upload",
    response_model=RFPUploadResponse,
    status_code=202,
    summary="Subir una RFP en PDF (modo ticket)",
    description=(
        "Recibe un PDF, crea el ticket en estado 'analizando', guarda el "
        "documento en data/raw/ y dispara el pipeline de agentes en background. "
        "Responde inmediatamente con el ticket_id para hacer polling."
    ),
)
async def upload_rfp(
    background_tasks: BackgroundTasks,
    file: UploadFile = None,  # type: ignore[assignment]
    db: Session = Depends(get_sql_session),
) -> JSONResponse:
    if file is None:
        raise HTTPException(status_code=400, detail={"error": "Falta el archivo PDF."})

    filename = file.filename or ""
    if not filename.lower().endswith(".pdf"):
        raise HTTPException(
            status_code=400,
            detail={"error": "Solo se admiten archivos PDF (.pdf)."},
        )

    content_type = (file.content_type or "").lower()
    if content_type and content_type not in _ALLOWED_CONTENT_TYPES:
        raise HTTPException(
            status_code=400,
            detail={"error": f"Tipo de contenido no soportado: {content_type}."},
        )

    pdf_bytes = await file.read()
    if not pdf_bytes:
        raise HTTPException(status_code=400, detail={"error": "El archivo esta vacio."})
    if len(pdf_bytes) > rfp_service.MAX_PDF_BYTES:
        raise HTTPException(
            status_code=413,
            detail={"error": f"El PDF supera el limite de {rfp_service.MAX_PDF_BYTES // (1024 * 1024)} MB."},
        )

    ticket = rfp_service.create_ticket_and_store_pdf(filename, pdf_bytes)

    # The pipeline (PDF→MD + clasificador + workers + synthesizer) runs AFTER
    # the response — minutes are possible, and the POST must stay fast.
    background_tasks.add_task(rfp_service.process_ticket, ticket.id)

    return JSONResponse(
        status_code=202,
        content={
            "ticket_id": ticket.id,
            "status": ticket.status,
            "detail": "RFP recibida. El analisis corre en segundo plano; consulta GET /rfp/tickets/{id}.",
        },
    )


@rfp_router.get(
    "/tickets",
    response_model=list[RFPTicketSummary],
    summary="Listar tickets RFP",
    description="Listado ordenado por fecha descendente; filtro opcional por estado.",
)
def list_rfp_tickets(
    status: str | None = None,
    db: Session = Depends(get_sql_session),
) -> list[RFPTicketSummary]:
    if status is not None:
        valid = {s.value for s in RFPStatus}
        if status not in valid:
            raise HTTPException(
                status_code=400,
                detail={"error": f"Estado invalido: {status}. Valores: {sorted(valid)}"},
            )
    return [_summary(ticket) for ticket in rfp_service.list_tickets(db, status)]


@rfp_router.get(
    "/tickets/{ticket_id}",
    response_model=RFPTicketDetail,
    summary="Detalle de un ticket RFP",
    description=(
        "Estado actual + metadatos + aspectos clave, borradores y evaluaciones "
        "por departamento + handoff de propuesta."
    ),
)
def get_rfp_ticket(
    ticket_id: str,
    db: Session = Depends(get_sql_session),
) -> RFPTicketDetail:
    bundle = rfp_service.get_ticket_bundle(db, ticket_id)
    if bundle is None:
        raise HTTPException(status_code=404, detail={"error": f"Ticket no encontrado: {ticket_id}"})
    ticket, document, sections = bundle
    return _detail(ticket, document, sections)


@rfp_router.post("/tickets/{ticket_id}/departments/{department_id}/decision")
def submit_rfp_department_decision(
    ticket_id: str,
    department_id: str,
    payload: RFPDecisionIn,
    session: Session = Depends(get_sql_session),
    current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    """Resume one department's durable graph; ownership is checked server-side."""
    try:
        from rfp_intake.approval import validate_decision
        decision = validate_decision(payload.model_dump())
        state = rfp_service.submit_department_decision(
            session,
            ticket_id=ticket_id,
            department_id=department_id,
            user_email=current_user.email,
            decision=decision,
        )
    except PermissionError as exc:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    except RuntimeError as exc:
        logger.exception("Runtime de aprobación RFP no disponible")
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail="El flujo de aprobación no está disponible.") from exc
    return {
        "ticket_id": ticket_id,
        "department_id": department_id,
        "approval_status": state.get("approval_status", "pending"),
        "iteration_count": state.get("iteration_count", 0),
        "status": session.get(RFPTicket, ticket_id).status,
    }


@rfp_router.get("/tickets/{ticket_id}/final-document")
def get_rfp_final_document(
    ticket_id: str,
    session: Session = Depends(get_sql_session),
    _current_user: User = Depends(get_current_user),
) -> dict[str, Any]:
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Ticket no encontrado.")
    if ticket.status != RFPStatus.COMPLETED.value:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="El documento final estará disponible tras todos los sign-offs y arbitrajes.")
    document = session.get(RFPFinalDocument, ticket_id)
    if document is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Documento final no encontrado.")
    return {
        "ticket_id": ticket_id,
        "sections": json.loads(document.sections),
        "currency": document.currency,
        "generated_at": document.generated_at,
    }
