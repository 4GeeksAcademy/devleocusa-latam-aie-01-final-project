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
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy.orm import selectinload  # noqa: F401  (kept for future joins)
from sqlmodel import Session, delete, select

from src import pipeline_adapter
from src.database import get_engine
from src.models.rfp import (
    DepartmentSection,
    RFPDocument,
    RFPTicket,
    RFPStatus,
    SectionStatus,
)

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
        result = pipeline_adapter.run_pipeline(
            ticket_id=ticket_id,
            pdf_path=pdf_path,
            artifacts_dir=_ticket_dir(ticket_id),
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
