"""SQLModel tables for the RFP intake flow (Parte 1) — Supabase PostgreSQL.

Persistence contract (mirrors the ticket lifecycle documented in the CONTEXT):

    RFPTicket        one row per uploaded PDF; drives the UI polling.
    RFPDocument      1-1 metadata + readability metrics of the converted doc.
    DepartmentSection  N-1 key aspects produced by the department workers.

Statuses used in Parte 1 (no ``esperando_aprobacion`` — that belongs to Parte 2):

    analizando  -> analisis_completo | descartado

TinyDB is NOT used for these models — Supabase PostgreSQL is the source of
truth, consistent with the inventory stack.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Optional
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_uuid() -> str:
    return str(uuid4())


class RFPStatus(str, Enum):
    """Lifecycle of an RFP ticket in Parte 1."""

    ANALIZANDO = "analizando"
    DESCARTADO = "descartado"
    ANALISIS_COMPLETO = "analisis_completo"
    GENERANDO_BORRADOR = "generando_borrador"
    EN_EVALUACION = "en_evaluación"
    NEEDS_HUMAN_REVIEW = "needs_human_review"


class DepartmentKey(str, Enum):
    """TrackFlow departments from CONTEXT-company.md (owners from the briefing)."""

    OPERACIONES_ALMACEN = "operaciones_almacen"          # Ana Whitfield
    ULTIMA_MILLA_TRANSPORTISTAS = "ultima_milla_transportistas"  # Carlos Vega
    LOGISTICA_INVERSA = "logistica_inversa"              # Sofia Ramos
    EXPERIENCIA_CLIENTE = "experiencia_cliente"          # Valentina Cruz
    COMERCIAL_CUENTAS = "comercial_cuentas"              # Miguel Torres
    TECNOLOGIA = "tecnologia"                            # Andres Kim
    DIRECCION_EJECUTIVA = "direccion_ejecutiva"          # CEO


#: Human-readable owner (contact) per department — straight from the CONTEXT.
DEPARTMENT_CONTACTS: dict[str, dict[str, str]] = {
    DepartmentKey.OPERACIONES_ALMACEN.value: {
        "contact_name": "Ana Whitfield",
        "contact_role": "Directora de Operaciones de Almacen",
    },
    DepartmentKey.ULTIMA_MILLA_TRANSPORTISTAS.value: {
        "contact_name": "Carlos Vega",
        "contact_role": "Head de Ultima Milla y Transportistas",
    },
    DepartmentKey.LOGISTICA_INVERSA.value: {
        "contact_name": "Sofia Ramos",
        "contact_role": "Lead de Logistica Inversa",
    },
    DepartmentKey.EXPERIENCIA_CLIENTE.value: {
        "contact_name": "Valentina Cruz",
        "contact_role": "CX Manager",
    },
    DepartmentKey.COMERCIAL_CUENTAS.value: {
        "contact_name": "Miguel Torres",
        "contact_role": "Head Comercial y Relacion con Clientes",
    },
    DepartmentKey.TECNOLOGIA.value: {
        "contact_name": "Andres Kim",
        "contact_role": "CTO",
    },
    DepartmentKey.DIRECCION_EJECUTIVA.value: {
        "contact_name": "CEO",
        "contact_role": "Direccion Ejecutiva",
    },
}


class SectionStatus(str, Enum):
    """Per-department worker outcome."""

    PENDIENTE = "pendiente"
    PROCESANDO = "procesando"
    COMPLETADO = "completado"
    ERROR = "error"


class RFPTicket(SQLModel, table=True):
    """One uploaded RFP document moving through the intake pipeline."""

    __tablename__ = "rfp_tickets"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    status: str = Field(
        default=RFPStatus.ANALIZANDO.value,
        max_length=30,
        nullable=False,
        index=True,
    )
    original_filename: str = Field(max_length=300, nullable=False)
    pdf_path: str = Field(max_length=600, nullable=False)
    markdown_path: Optional[str] = Field(default=None, max_length=600)

    # Classifier outcome (kept on the ticket so a rejection is auditable).
    is_rfp: Optional[bool] = Field(default=None)
    classification_confidence: Optional[float] = Field(default=None)
    classification_reason: Optional[str] = Field(default=None)

    #: Free-text explanation shown to Ventas when status == descartado.
    error_detail: Optional[str] = Field(default=None)

    #: Consolidated synthesizer summary (what each department must do + who owns it).
    synthesis_summary: Optional[str] = Field(default=None)

    #: JSON-serialized handoff payload for Parte 2 (workstreams + key_aspects).
    handoff_payload: Optional[str] = Field(default=None)

    #: Queue flag for Parte 2: rows with status=analisis_completo AND
    #: dispatched_at IS NULL are pending pickup. No second API needed.
    dispatched_at: Optional[datetime] = Field(default=None)
    proposal_completed_at: Optional[datetime] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)


class RFPDocument(SQLModel, table=True):
    """Extracted metadata + readability metrics, one row per processed document."""

    __tablename__ = "rfp_documents"

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    ticket_id: str = Field(nullable=False, index=True)

    # Metadata extracted from the converted Markdown.
    title: Optional[str] = Field(default=None, max_length=400)
    issuing_organization: Optional[str] = Field(default=None, max_length=300)
    rfp_reference: Optional[str] = Field(default=None, max_length=120)
    proposal_due_date: Optional[str] = Field(default=None, max_length=60)
    contact_name: Optional[str] = Field(default=None, max_length=200)
    contact_email: Optional[str] = Field(default=None, max_length=254)
    detected_language: Optional[str] = Field(default=None, max_length=10)

    #: Full JSON blob of every extra field the extractor could pull.
    extra_metadata: Optional[str] = Field(default=None)

    # Readability / cost estimation (py-readability-metrics over the Markdown).
    word_count: Optional[int] = Field(default=None)
    flesch_kincaid_grade: Optional[float] = Field(default=None)
    gunning_fog_index: Optional[float] = Field(default=None)
    coleman_liau_index: Optional[float] = Field(default=None)
    estimated_token_cost: Optional[int] = Field(default=None)

    created_at: datetime = Field(default_factory=_utcnow, nullable=False)


class DepartmentSection(SQLModel, table=True):
    """Key aspects for one department of one RFP (worker output, synthesizer input)."""

    __tablename__ = "rfp_department_sections"
    __table_args__ = {"sqlite_autoincrement": False}

    id: str = Field(default_factory=_new_uuid, primary_key=True)
    ticket_id: str = Field(nullable=False, index=True)
    department: str = Field(max_length=60, nullable=False)

    #: Internal TrackFlow owner to ask for this department's input (from CONTEXT).
    contact_name: Optional[str] = Field(default=None, max_length=200)
    contact_role: Optional[str] = Field(default=None, max_length=200)

    #: JSON: {resumen_requisitos, entregables, cifras_citadas[], preguntas_abiertas[],
    #:        missing_data[], prioridad} — cifras_citadas are LITERAL quotes only.
    key_aspects: Optional[str] = Field(default=None)

    status: str = Field(default=SectionStatus.PENDIENTE.value, max_length=20, nullable=False)
    worker_error: Optional[str] = Field(default=None)

    #: Parte 2 artifacts, retained even when human review is required.
    proposal_draft: Optional[str] = Field(default=None)
    evaluation_result: Optional[str] = Field(default=None)
    iteration_count: int = Field(default=0, nullable=False)

    created_at: datetime = Field(default_factory=_utcnow, nullable=False)
    updated_at: datetime = Field(default_factory=_utcnow, nullable=False)
