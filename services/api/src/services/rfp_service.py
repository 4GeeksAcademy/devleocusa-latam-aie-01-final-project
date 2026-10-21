"""RFP intake service — ticket lifecycle + Supabase persistence.

The pipeline (``data/pipelines/src/rfp_intake``) is pure: it converts,
classifies and synthesizes without touching the database. This service owns
every write:

    create_ticket_and_store_pdf()  receiving step (status = analizando)
    process_ticket()               background job: run pipeline → persist
    list_tickets() / get_ticket()  read side for the UI polling

All rows go to Supabase PostgreSQL via SQLModel — TinyDB is never used here.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import selectinload  # noqa: F401  (kept for future joins)
from sqlalchemy import update
from sqlmodel import Session, delete, select

from src import pipeline_adapter
from src.database import get_engine
from src.models.rfp import (
    DepartmentSection,
    HITO9_DEPARTMENT_APPROVERS,
    RFPDocument,
    RFPFinalDocument,
    RFPNodeTrace,
    RFPTicket,
    RFPStatus,
    SectionStatus,
    LEGACY_TO_HITO9_DEPARTMENT,
)
from src.services.user_service import get_user_by_email
from src.services.rfp_event_service import RFP_TICKET_CREATED, rfp_event_broker

logger = logging.getLogger(__name__)

#: Upload size guard (RFPs are text PDFs; anything bigger is suspicious).
MAX_PDF_BYTES: int = 25 * 1024 * 1024  # 25 MB

#: Repo-root/data/raw — runtime artifact directory for received documents.
RAW_DATA_DIR: Path = Path(__file__).resolve().parents[4] / "data" / "raw"

_SAFE_NAME_RE = re.compile(r"[^A-Za-z0-9._-]+")


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _safe_filename(filename: str) -> str:
    cleaned = _SAFE_NAME_RE.sub("_", Path(filename).name).strip("._")
    return cleaned or f"rfp_{uuid4().hex[:8]}.pdf"


def _ticket_dir(ticket_id: str) -> Path:
    return RAW_DATA_DIR / ticket_id


# ── Receiving step (called from the POST endpoint) ──────────────────────


def create_ticket_and_store_pdf(original_filename: str, pdf_bytes: bytes) -> RFPTicket:
    """Persist the ticket (``analizando``) and the PDF under ``data/raw/``."""
    ticket_id = str(uuid4())
    ticket_dir = _ticket_dir(ticket_id)
    ticket_dir.mkdir(parents=True, exist_ok=True)

    pdf_path = ticket_dir / _safe_filename(original_filename)
    if not pdf_path.name.lower().endswith(".pdf"):
        pdf_path = pdf_path.with_suffix(".pdf")
    pdf_path.write_bytes(pdf_bytes)

    ticket = RFPTicket(
        id=ticket_id,
        status=RFPStatus.ANALIZANDO.value,
        original_filename=original_filename[:300],
        pdf_path=str(pdf_path),
    )
    with Session(get_engine()) as session:
        session.add(ticket)
        session.commit()
        session.refresh(ticket)
    logger.info("RFP ticket %s creado (analizando) — %s", ticket_id, original_filename)
    return ticket


# ── Background processing ───────────────────────────────────────────────


def _clear_previous_results(session: Session, ticket_id: str) -> None:
    """Remove previous document/section rows so reprocessing is idempotent."""
    session.exec(delete(DepartmentSection).where(DepartmentSection.ticket_id == ticket_id))
    session.exec(delete(RFPDocument).where(RFPDocument.ticket_id == ticket_id))


def _persist_document(session: Session, ticket_id: str, result: Any) -> None:
    metadata: dict[str, Any] = result.metadata or {}
    readability: dict[str, Any] = result.readability or {}
    document = RFPDocument(
        ticket_id=ticket_id,
        title=metadata.get("title"),
        issuing_organization=metadata.get("issuing_organization"),
        rfp_reference=metadata.get("rfp_reference"),
        proposal_due_date=metadata.get("proposal_due_date"),
        contact_name=metadata.get("contact_name"),
        contact_email=metadata.get("contact_email"),
        detected_language=metadata.get("detected_language"),
        extra_metadata=json.dumps(metadata.get("extra", {}), ensure_ascii=False),
        word_count=readability.get("word_count"),
        flesch_kincaid_grade=readability.get("flesch_kincaid_grade"),
        gunning_fog_index=readability.get("gunning_fog_index"),
        coleman_liau_index=readability.get("coleman_liau_index"),
        estimated_token_cost=readability.get("estimated_token_cost"),
    )
    session.add(document)


def _persist_sections(session: Session, ticket_id: str, result: Any) -> None:
    now = _utcnow()
    for section in result.sections:
        session.add(
            DepartmentSection(
                ticket_id=ticket_id,
                department=str(section.get("department", ""))[:60],
                contact_name=section.get("contact_name"),
                contact_role=section.get("contact_role"),
                key_aspects=json.dumps(section.get("key_aspects"), ensure_ascii=False)
                if section.get("key_aspects")
                else None,
                status=str(section.get("status", SectionStatus.PENDIENTE.value))[:20],
                worker_error=section.get("worker_error"),
                updated_at=now,
            )
        )


def process_ticket(ticket_id: str) -> None:
    """Background job: run the intake pipeline and persist every transition.

    Ticket-state truth (D5): this function NEVER leaves a ticket in
    ``analizando``. Success → ``analisis_completo``; rejection or document
    error → ``descartado`` with ``error_detail``; unexpected infrastructure
    failure → ``descartado`` with the exception message.
    """
    with Session(get_engine()) as session:
        ticket = session.get(RFPTicket, ticket_id)
        if ticket is None:
            logger.error("RFP ticket %s no encontrado para procesar", ticket_id)
            return
        pdf_path = Path(ticket.pdf_path)

    try:
        def notify_classified(
            classified_ticket_id: str,
            metadata: dict[str, Any],
            departments: list[str],
        ) -> None:
            # The classifier callback runs only for a positive RFP decision.
            # Supabase remains authoritative; this is a transient notification.
            try:
                normalized = metadata or {}
                extra = normalized.get("extra") or {}
                if not isinstance(extra, dict):
                    extra = {}

                def known_value(*values: Any) -> Any:
                    return next(
                        (value for value in values if value not in (None, "")),
                        None,
                    )

                # Only use fields explicitly extracted as the same domain
                # field. In particular, issuing_organization is not assumed
                # to be client_name, and rfp_reference is not an internal ID.
                rfp_event_broker.publish({
                    "event": RFP_TICKET_CREATED,
                    "data": {
                        "ticket_id": classified_ticket_id,
                        "rfp_id": known_value(normalized.get("rfp_id"), extra.get("rfp_id")),
                        "client_name": known_value(normalized.get("client_name"), extra.get("client_name")),
                        "client_country": known_value(normalized.get("client_country"), extra.get("client_country")),
                        "services_requested": list(departments),
                        "status": "analyzing",
                        "created_at": ticket_created_at.isoformat(),
                    },
                })
            except Exception:
                # Transient delivery must never turn a positive classification
                # into a failed intake run; the persisted Supabase row is truth.
                logger.exception("No se pudo publicar evento SSE para ticket %s", classified_ticket_id)

        with Session(get_engine()) as session:
            persisted_ticket = session.get(RFPTicket, ticket_id)
            ticket_created_at = (
                persisted_ticket.created_at if persisted_ticket is not None else _utcnow()
            )

        result = pipeline_adapter.run_pipeline(
            ticket_id=ticket_id,
            pdf_path=pdf_path,
            artifacts_dir=_ticket_dir(ticket_id),
            on_classified=notify_classified,
        )
    except Exception as exc:  # infra failure (LLM down, disk, ...) — never hang
        logger.exception("RFP ticket %s fallo el pipeline", ticket_id)
        with Session(get_engine()) as session:
            ticket = session.get(RFPTicket, ticket_id)
            if ticket is not None:
                ticket.status = RFPStatus.DESCARTADO.value
                ticket.error_detail = f"Error de procesamiento: {exc}"
                ticket.updated_at = _utcnow()
                session.add(ticket)
                session.commit()
        return

    with Session(get_engine()) as session:
        ticket = session.get(RFPTicket, ticket_id)
        if ticket is None:
            return

        # Reprocess-safe: drop artifacts from any previous run of this ticket.
        _clear_previous_results(session, ticket_id)

        ticket.status = result.status
        # A successful run must clear any stale error from a previous attempt.
        ticket.error_detail = (
            None
            if result.status == pipeline_adapter.status_analisis_completo()
            else result.error_detail
        )
        ticket.markdown_path = result.markdown_path
        ticket.is_rfp = result.is_rfp
        ticket.classification_confidence = result.classification_confidence
        ticket.classification_reason = result.classification_reason
        ticket.synthesis_summary = result.synthesis_summary
        ticket.updated_at = _utcnow()

        if result.unmapped_mentions:
            note = f" (menciones fuera del catalogo: {', '.join(result.unmapped_mentions)})"
            ticket.classification_reason = f"{ticket.classification_reason or ''}{note}".strip()

        if result.status == pipeline_adapter.status_descartado():
            ticket.error_detail = result.error_detail
        else:
            ticket.handoff_payload = (
                json.dumps(result.handoff_payload, ensure_ascii=False)
                if result.handoff_payload
                else None
            )
            _persist_document(session, ticket_id, result)
            _persist_sections(session, ticket_id, result)

        # Rejected documents also get their metadata persisted (auditable).
        if result.status == pipeline_adapter.status_descartado() and result.metadata:
            _persist_document(session, ticket_id, result)

        session.add(ticket)
        session.commit()
    logger.info("RFP ticket %s terminado como %s", ticket_id, result.status)


# ── Read side (UI polling) ──────────────────────────────────────────────


def list_tickets(session: Session, status: str | None = None) -> list[RFPTicket]:
    statement = select(RFPTicket).order_by(RFPTicket.created_at.desc())
    if status:
        statement = statement.where(RFPTicket.status == status)
    return list(session.exec(statement).all())


def get_ticket_bundle(
    session: Session, ticket_id: str
) -> tuple[RFPTicket, RFPDocument | None, list[DepartmentSection]] | None:
    """Ticket + its document row + its department sections (or None)."""
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        return None
    document = session.exec(
        select(RFPDocument).where(RFPDocument.ticket_id == ticket_id)
    ).first()
    sections = list(
        session.exec(
            select(DepartmentSection)
            .where(DepartmentSection.ticket_id == ticket_id)
            .order_by(DepartmentSection.created_at)
        ).all()
    )
    return ticket, document, sections


# ── Parte 2 proposal generation ────────────────────────────────────────

def claim_next_proposal_ticket(session: Session, ticket_id: str | None = None) -> RFPTicket | None:
    """Atomically claim one pending handoff, optionally restricting to one ticket."""
    statement = (
        select(RFPTicket.id)
        .where(
            RFPTicket.status == RFPStatus.ANALISIS_COMPLETO.value,
            RFPTicket.dispatched_at.is_(None),
            RFPTicket.handoff_payload.is_not(None),
        )
        .order_by(RFPTicket.created_at)
        .limit(1)
    )
    if ticket_id is not None:
        statement = statement.where(RFPTicket.id == ticket_id)
    candidate = session.exec(statement).first()
    if candidate is None:
        return None
    now = _utcnow()
    claimed = session.exec(
        update(RFPTicket)
        .where(
            RFPTicket.id == candidate,
            RFPTicket.status == RFPStatus.ANALISIS_COMPLETO.value,
            RFPTicket.dispatched_at.is_(None),
        )
        .values(dispatched_at=now, status=RFPStatus.GENERANDO_BORRADOR.value, updated_at=now)
        .returning(RFPTicket.id)
    ).first()
    if claimed is None:
        session.rollback()
        return None
    session.commit()
    return session.get(RFPTicket, claimed)


def set_proposal_status(session: Session, ticket_id: str, status: str) -> None:
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket no encontrado: {ticket_id}")
    ticket.status = status
    ticket.updated_at = _utcnow()
    session.add(ticket)
    session.commit()


def persist_proposal_section(
    session: Session, ticket_id: str, department: str, update: dict[str, Any]
) -> None:
    """Persist latest section snapshot after each generation/evaluation transition."""
    section = session.exec(
        select(DepartmentSection).where(
            DepartmentSection.ticket_id == ticket_id,
            DepartmentSection.department == department,
        )
    ).first()
    if section is None:
        raise ValueError(f"Sección {department} no existe en ticket {ticket_id}")
    if update.get("draft") is not None:
        section.proposal_draft = str(update["draft"])
    if "evaluation_result" in update:
        section.evaluation_result = (
            json.dumps(update["evaluation_result"], ensure_ascii=False)
            if update["evaluation_result"] is not None
            else None
        )
    if update.get("iteration_count") is not None:
        section.iteration_count = int(update["iteration_count"])
    section.status = str(update.get("status", section.status))[:30]
    section.worker_error = update.get("error")
    section.updated_at = _utcnow()
    session.add(section)
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is not None:
        ticket.updated_at = _utcnow()
        session.add(ticket)
    session.commit()


def persist_proposal_handoff(session: Session, ticket_id: str, payload: dict[str, Any]) -> None:
    """Persist complete Part 3 handoff; failed sections remain included."""
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket no encontrado: {ticket_id}")
    ticket.handoff_payload = json.dumps(payload, ensure_ascii=False)
    ticket.proposal_completed_at = _utcnow()
    ticket.status = (
        RFPStatus.NEEDS_HUMAN_REVIEW.value
        if payload.get("needs_human_review")
        else RFPStatus.ANALISIS_COMPLETO.value
    )
    ticket.updated_at = _utcnow()
    session.add(ticket)
    session.commit()


def process_next_proposal_ticket(max_iterations: int = 3, ticket_id: str | None = None) -> str | None:
    """Claim one Part 1 handoff; optionally target a ticket instead of global FIFO."""
    with Session(get_engine()) as session:
        ticket = claim_next_proposal_ticket(session, ticket_id=ticket_id)
        if ticket is None:
            return None
        ticket_id = ticket.id
        try:
            handoff = json.loads(ticket.handoff_payload or "{}")
        except json.JSONDecodeError as exc:
            ticket.status = RFPStatus.NEEDS_HUMAN_REVIEW.value
            ticket.error_detail = f"Handoff inválido para Parte 2: {exc}"
            ticket.updated_at = _utcnow()
            session.add(ticket)
            session.commit()
            return ticket_id

    # Hito 9 activates only three departments; keep legacy rows but exclude the rest.
    canonical_to_legacy = {value: key for key, value in LEGACY_TO_HITO9_DEPARTMENT.items()}
    active_workstreams = []
    for item in handoff.get("workstreams", []):
        if not isinstance(item, dict):
            continue
        department = str(item.get("department", ""))
        if department in LEGACY_TO_HITO9_DEPARTMENT:
            active_workstreams.append(item)
        elif department in canonical_to_legacy:
            active_workstreams.append({**item, "department": canonical_to_legacy[department]})
    handoff["workstreams"] = active_workstreams

    def on_update(department: str, update_payload: dict[str, Any]) -> None:
        with Session(get_engine()) as session:
            if update_payload.get("status") == "en_evaluación":
                set_proposal_status(session, ticket_id, RFPStatus.EN_EVALUACION.value)
            elif update_payload.get("status") == "generando_borrador":
                set_proposal_status(session, ticket_id, RFPStatus.GENERANDO_BORRADOR.value)
            persist_proposal_section(session, ticket_id, department, update_payload)

    try:
        result = pipeline_adapter.run_proposal_handoff(
            handoff,
            max_iterations=max_iterations,
            on_update=on_update,
            generator=pipeline_adapter.proposal_helpers()[0],
        )
        def persist_live_trace(event: dict[str, Any]) -> None:
            with Session(get_engine()) as trace_session:
                _persist_trace_event(trace_session, ticket_id, event)
        with pipeline_adapter.department_approval_runtime(on_trace=persist_live_trace) as graph:
            with Session(get_engine()) as session:
                persist_proposal_handoff(session, ticket_id, result)
                # Parte 2's exhausted evaluator budget still hands its last
                # draft to the department owner for an explicit sign-off.
                begin_human_approval(session, ticket_id, graph=graph, max_iterations=max_iterations)
    except Exception as exc:
        logger.exception("Parte 2 falló en ticket %s", ticket_id)
        with Session(get_engine()) as session:
            ticket = session.get(RFPTicket, ticket_id)
            if ticket is not None:
                ticket.status = RFPStatus.NEEDS_HUMAN_REVIEW.value
                ticket.error_detail = f"Error de propuesta; borradores conservados: {exc}"
                ticket.updated_at = _utcnow()
                session.add(ticket)
                session.commit()
    return ticket_id


def _canonical_handoff(ticket: RFPTicket, sections: list[DepartmentSection]) -> dict[str, Any]:
    """Return exactly the active Hito 9 workstreams, retaining Part 1 aspects."""
    raw = json.loads(ticket.handoff_payload or "{}")
    source = raw.get("workstreams") or raw.get("handoff") or []
    by_department = {str(item.get("department", "")): item for item in source if isinstance(item, dict)}
    existing_proposals = raw.get("proposal_sections", [])
    workstreams: list[dict[str, Any]] = []
    for section in sections:
        department_id = LEGACY_TO_HITO9_DEPARTMENT.get(section.department, section.department)
        if department_id not in HITO9_DEPARTMENT_APPROVERS:
            continue
        workstream = by_department.get(section.department, by_department.get(department_id, {}))
        aspects = json.loads(section.key_aspects) if section.key_aspects else workstream.get("key_aspects", {})
        workstreams.append({
            **workstream,
            "department": department_id,
            "key_aspects": aspects if isinstance(aspects, dict) else {},
        })
        section.department_id = department_id
        section.approver = HITO9_DEPARTMENT_APPROVERS[department_id]
        section.updated_at = _utcnow()
    return {
        "ticket_id": ticket.id,
        "synthesizer_summary": ticket.synthesis_summary or raw.get("synthesizer_summary") or "",
        "workstreams": workstreams,
        "proposal_sections": existing_proposals,
        "country": raw.get("country") or raw.get("client_country") or raw.get("pais"),
    }


def begin_human_approval(session: Session, ticket_id: str, *, graph: Any, max_iterations: int = 3) -> None:
    """Generate all active sections independently and persist each interrupt."""
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        raise ValueError(f"Ticket no encontrado: {ticket_id}")
    sections = list(session.exec(select(DepartmentSection).where(DepartmentSection.ticket_id == ticket_id)).all())
    handoff = _canonical_handoff(ticket, sections)
    active_ids = {workstream["department"] for workstream in handoff["workstreams"]}
    for section in sections:
        normalized = LEGACY_TO_HITO9_DEPARTMENT.get(section.department, section.department)
        if normalized not in active_ids:
            section.department_id = None
    session.add_all(sections)
    session.commit()
    if not handoff["workstreams"]:
        raise ValueError("El handoff no contiene departamentos Hito 9 activos.")

    generator, evaluator = pipeline_adapter.proposal_helpers()
    ticket.status = RFPStatus.GENERANDO_BORRADOR.value
    session.add(ticket)
    session.commit()
    # Isolate each workstream. An interrupt in one graph does not block peers.
    proposal_results = {LEGACY_TO_HITO9_DEPARTMENT.get(str(item.get("department", "")), str(item.get("department", ""))): item
                        for item in handoff.get("proposal_sections", []) if isinstance(item, dict)}
    for workstream in handoff["workstreams"]:
        department_id = workstream["department"]
        proposal = proposal_results.get(department_id, {})
        evaluation = proposal.get("evaluation_result") or {}
        state = pipeline_adapter.invoke_department_approval(
            graph,
            ticket_id=ticket_id,
            department_id=department_id,
            workstream=workstream,
            summary=handoff["synthesizer_summary"],
            max_iterations=max_iterations,
            generator=generator,
            evaluator=evaluator,
            initial_draft=str(proposal.get("draft") or ""),
            initial_evaluation=evaluation if isinstance(evaluation, dict) else {},
            initial_iteration_count=int(proposal.get("iteration_count", 0)),
        )
        _persist_approval_state(session, ticket_id, department_id, state)
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is not None:
        ticket.status = RFPStatus.WAITING_APPROVAL.value
        ticket.updated_at = _utcnow()
        session.add(ticket)
        session.commit()


def _persist_approval_state(session: Session, ticket_id: str, department_id: str, state: dict[str, Any]) -> None:
    section = session.exec(select(DepartmentSection).where(
        DepartmentSection.ticket_id == ticket_id,
        DepartmentSection.department_id == department_id,
    )).first()
    if section is None:
        raise ValueError(f"Sección Hito 9 ausente: {department_id}")
    section.proposal_draft = str(state.get("draft") or section.proposal_draft or "")
    section.evaluation_result = json.dumps(state.get("evaluation_result") or {}, ensure_ascii=False)
    section.approval_iteration_count = int(state.get("iteration_count", section.approval_iteration_count))
    section.approval_status = str(state.get("approval_status", "pending"))
    section.status = SectionStatus.COMPLETADO.value if section.approval_status == "approved" else SectionStatus.PROCESANDO.value
    section.updated_at = _utcnow()
    session.add(section)
    for event in state.get("trace", []):
        _persist_trace_event(session, ticket_id, event, department_id=department_id)
    session.commit()


def _persist_trace_event(
    session: Session, ticket_id: str, event: dict[str, Any], *, department_id: str | None = None
) -> None:
    """Append a trace exactly once across interrupt/resume cycles."""
    thread_id = str(event.get("thread_id") or "")
    if not thread_id:
        department_id = department_id or str(event.get("department_id") or "")
        if not department_id:
            raise ValueError("La traza RFP requiere department_id.")
        thread_id = f"rfp-{ticket_id}:{department_id}"
    department_id = department_id or thread_id.rsplit(":", 1)[-1]
    raw_input = json.dumps(event.get("input"), ensure_ascii=False, default=str)
    raw_output = json.dumps(event.get("output"), ensure_ascii=False, default=str)
    existing = session.exec(select(RFPNodeTrace).where(
        RFPNodeTrace.thread_id == thread_id,
        RFPNodeTrace.node == str(event["node"]),
        RFPNodeTrace.input == raw_input,
        RFPNodeTrace.output == raw_output,
    )).first()
    if existing is not None:
        return
    previous = session.exec(select(RFPNodeTrace.sequence).where(
        RFPNodeTrace.thread_id == thread_id,
    ).order_by(RFPNodeTrace.sequence.desc()).limit(1)).first()
    session.add(RFPNodeTrace(
        ticket_id=ticket_id,
        department_id=department_id,
        thread_id=thread_id,
        sequence=(int(previous) if previous is not None else 0) + 1,
        node=str(event["node"]),
        agent=str(event["agent"]),
        input=raw_input,
        output=raw_output,
        occurred_at=datetime.fromisoformat(str(event["timestamp"])),
    ))
    session.commit()


def submit_department_decision(
    session: Session, *, ticket_id: str, department_id: str,
    user_email: str, decision: dict[str, str],
) -> dict[str, Any]:
    if department_id not in HITO9_DEPARTMENT_APPROVERS:
        raise ValueError("Departamento inválido.")
    assigned_email = _approver_email(department_id)
    if assigned_email.casefold().endswith(".example") and (
        not os.getenv("RFP_ALLOW_TEST_APPROVERS", "").casefold() == "true"
        or ticket_id != os.getenv("RFP_APPROVER_TEST_TICKET_ID", "").strip()
    ):
        raise PermissionError("La identidad de prueba solo puede aprobar el ticket sintético configurado.")
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        raise LookupError("Ticket no encontrado.")
    if user_email.casefold() != assigned_email.casefold():
        raise PermissionError("El usuario autenticado no es el aprobador asignado.")
    section = session.exec(select(DepartmentSection).where(
        DepartmentSection.ticket_id == ticket_id,
        DepartmentSection.department_id == department_id,
    )).first()
    if section is None:
        raise LookupError("Sección no encontrada.")
    if ticket.status != RFPStatus.WAITING_APPROVAL.value:
        raise ValueError("El ticket no está esperando aprobación.")
    if section.approval_status in {"approved", "needs_human_review"}:
        raise ValueError("La sección ya no admite decisiones.")
    if section.approval_iteration_count >= 3 and decision["decision"] != "approve":
        section.approval_status = "needs_human_review"
        session.add(section)
        session.commit()
        raise ValueError("Se alcanzó el máximo de iteraciones humanas.")

    return _submit_decision_with_runtime(
        session, ticket, section, department_id, user_email, decision,
    )


def _submit_decision_with_runtime(
    session: Session, ticket: RFPTicket, section: DepartmentSection,
    department_id: str, user_email: str, decision: dict[str, str],
) -> dict[str, Any]:
    workstream = {"department": department_id, "key_aspects": json.loads(section.key_aspects or "{}")}
    generator, evaluator = pipeline_adapter.proposal_helpers()
    def persist_live_trace(event: dict[str, Any]) -> None:
        with Session(get_engine()) as trace_session:
            _persist_trace_event(trace_session, ticket.id, event)

    with pipeline_adapter.department_approval_runtime(on_trace=persist_live_trace) as graph:
        state = pipeline_adapter.invoke_department_approval(
            graph, ticket_id=ticket.id, department_id=department_id,
            workstream=workstream, summary=ticket.synthesis_summary or "",
            max_iterations=3, generator=generator, evaluator=evaluator, resume=decision,
        )
    _persist_approval_state(session, ticket_id, department_id, state)
    section = session.exec(select(DepartmentSection).where(
        DepartmentSection.ticket_id == ticket_id,
        DepartmentSection.department_id == department_id,
    )).first()
    assert section is not None
    section.approver = HITO9_DEPARTMENT_APPROVERS[department_id]
    section.approval_comment = decision.get("comment") or None
    if state.get("approval_status") == "approved":
        section.approved_at = _utcnow()
    session.add(section)
    session.commit()
    _arbitrate_and_finalize(session, ticket.id)
    return state


def _approver_email(department_id: str) -> str:
    """Map assigned briefing owners to registered TrackFlow identities."""
    key = f"RFP_APPROVER_{department_id.upper()}_EMAIL"
    email = os.getenv(key, "").strip()
    if not email and os.getenv("RFP_ALLOW_TEST_APPROVERS", "").casefold() == "true":
        email = os.getenv(f"RFP_TEST_APPROVER_{department_id.upper()}_EMAIL", "").strip()
    is_test_email = email.casefold().endswith(".example")
    if is_test_email:
        if os.getenv("RFP_ALLOW_TEST_APPROVERS", "").casefold() != "true":
            raise PermissionError("Las identidades .example requieren RFP_ALLOW_TEST_APPROVERS=true.")
        if not os.getenv("RFP_APPROVER_TEST_TICKET_ID", "").strip():
            raise PermissionError("RFP_APPROVER_TEST_TICKET_ID debe identificar el ticket sintético.")
        test_user = get_user_by_email(email)
        if test_user is None or not test_user.is_active:
            raise PermissionError("La identidad de prueba no está registrada y activa.")
    if not email:
        raise PermissionError(f"No existe mapeo de identidad para {department_id}; configure {key}.")
    return email


def _arbitrate_and_finalize(session: Session, ticket_id: str) -> None:
    ticket = session.get(RFPTicket, ticket_id)
    if ticket is None:
        return
    sections = list(session.exec(select(DepartmentSection).where(
        DepartmentSection.ticket_id == ticket_id,
        DepartmentSection.department_id.is_not(None),
    )).all())
    structured = []
    for section in sections:
        aspects = json.loads(section.key_aspects or "{}")
        structured.append({"department_id": section.department_id, **aspects})
    country = ""
    handoff = json.loads(ticket.handoff_payload or "{}")
    for key in ("country", "client_country", "pais"):
        if handoff.get(key):
            country = str(handoff[key])
            break
    if not country:
        document = session.exec(select(RFPDocument).where(RFPDocument.ticket_id == ticket_id)).first()
        if document is not None and document.extra_metadata:
            try:
                metadata = json.loads(document.extra_metadata)
                country = str(metadata.get("client_country") or metadata.get("country") or "")
            except (TypeError, json.JSONDecodeError):
                country = ""
    arbitration = pipeline_adapter.arbitrate_conflicts(structured, client_country=country)
    if arbitration["blocked"]:
        ticket.status = RFPStatus.WAITING_APPROVAL.value
        ticket.error_detail = "Arbitraje pendiente: " + ", ".join(c["trigger_id"] for c in arbitration["conflicts"])
        session.add(ticket)
        session.commit()
        return
    if sections and all(section.approval_status == "approved" for section in sections):
        payload = [
            {"department_id": section.department_id, "approver": section.approver,
             "text": section.proposal_draft, "approved_at": section.approved_at.isoformat() if section.approved_at else None}
            for section in sections
        ]
        document = session.get(RFPFinalDocument, ticket_id) or RFPFinalDocument(ticket_id=ticket_id, sections="[]", currency="USD")
        document.sections = json.dumps(payload, ensure_ascii=False)
        document.currency = "EUR" if country.casefold() in {"spain", "españa", "espana"} else "USD"
        document.generated_at = _utcnow()
        ticket.status = RFPStatus.COMPLETED.value
        ticket.error_detail = None
        ticket.updated_at = _utcnow()
        session.add(document)
        session.add(ticket)
        session.commit()
