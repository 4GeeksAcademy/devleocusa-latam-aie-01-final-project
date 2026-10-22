"""End-to-end runner for the rfp_intake pipeline (no database access).

Responsibilities: PDF → Markdown, metadata + readability, graph execution,
and assembly of the Parte 2 handoff payload. Persistence and ticket-state
bookkeeping belong to the caller (``services/api/src/services/rfp_service.py``
for the HTTP flow, ``scripts/rfp_intake.py`` for manual runs).
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from .conversion import ConversionError, convert_pdf_to_markdown
from .state import RFPIntakeState
from .graph import build_graph
from .metadata import extract_metadata, compute_readability

#: Ticket statuses (Parte 1 vocabulary — must match services/api models).
STATUS_DESCARTADO = "descartado"
STATUS_ANALISIS_COMPLETO = "analisis_completo"


@dataclass
class IntakeResult:
    """Everything the caller needs to persist the ticket outcome."""

    ticket_id: str
    status: str
    markdown_path: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)
    readability: dict[str, Any] = field(default_factory=dict)
    is_rfp: bool | None = None
    classification_confidence: float | None = None
    classification_reason: str | None = None
    unmapped_mentions: list[str] = field(default_factory=list)
    sections: list[dict[str, Any]] = field(default_factory=list)
    synthesis_summary: str | None = None
    handoff_payload: dict[str, Any] | None = None
    error_detail: str | None = None


def _as_state(final_state: Any) -> RFPIntakeState:
    """LangGraph returns the final state as a plain dict — normalize to the dataclass."""
    if isinstance(final_state, RFPIntakeState):
        return final_state
    known = set(RFPIntakeState.__dataclass_fields__)
    return RFPIntakeState(**{k: v for k, v in dict(final_state).items() if k in known})


def _build_handoff(
    ticket_id: str,
    markdown_path: Path,
    synthesis: dict[str, Any] | None,
) -> dict[str, Any]:
    """Handoff contract for Parte 2: no PDF re-parsing required."""
    return {
        "ticket_id": ticket_id,
        "markdown_path": str(markdown_path),
        "workstreams": (synthesis or {}).get("handoff", []),
        "synthesizer_summary": (synthesis or {}).get("resumen", ""),
        "contradicciones": (synthesis or {}).get("contradicciones", []),
    }


def run_pipeline(
    ticket_id: str,
    pdf_path: Path,
    artifacts_dir: Path | None = None,
    *,
    on_classified: Any = None,
) -> IntakeResult:
    """Run the full intake pipeline for one uploaded PDF.

    Never raises for document-level problems: a broken PDF or a rejection both
    produce a terminal ``IntakeResult`` with ``status=descartado`` and a
    human-readable ``error_detail``. Infrastructure failures (e.g. the LLM
    endpoint being down) DO propagate so the caller can decide.
    """
    pdf_path = Path(pdf_path)
    artifacts_dir = Path(artifacts_dir) if artifacts_dir else pdf_path.parent

    # ── 1. PDF → Markdown ───────────────────────────────────────────────
    try:
        conversion = convert_pdf_to_markdown(pdf_path, artifacts_dir)
    except ConversionError as exc:
        return IntakeResult(
            ticket_id=ticket_id,
            status=STATUS_DESCARTADO,
            error_detail=str(exc),
        )
    markdown_path = conversion.markdown_path
    markdown = markdown_path.read_text(encoding="utf-8")

    # ── 2. Metadata + readability ───────────────────────────────────────
    metadata = extract_metadata(markdown).to_dict()
    readability = compute_readability(markdown).to_dict()

    # ── 3. Graph: classifier → orchestrator → workers → synthesizer ─────
    graph = build_graph(on_classified=on_classified)
    final_state = graph.invoke(
        {
            "ticket_id": ticket_id,
            "markdown": markdown,
            "metadata": metadata,
            "readability": readability,
        }
    )
    final_state = _as_state(final_state)

    # ── 4. Assemble outcome ─────────────────────────────────────────────
    if not final_state.is_rfp:
        reason = final_state.classification_reason or "El documento no es una RFP valida."
        error_detail = final_state.error or reason  # low-confidence note, if any
        return IntakeResult(
            ticket_id=ticket_id,
            status=STATUS_DESCARTADO,
            markdown_path=str(markdown_path),
            metadata=metadata,
            readability=readability,
            is_rfp=False,
            classification_confidence=final_state.classification_confidence,
            classification_reason=reason,
            unmapped_mentions=final_state.unmapped_mentions,
            error_detail=error_detail,
        )

    synthesis = final_state.synthesis or {}
    return IntakeResult(
        ticket_id=ticket_id,
        status=STATUS_ANALISIS_COMPLETO,
        markdown_path=str(markdown_path),
        metadata=metadata,
        readability=readability,
        is_rfp=True,
        classification_confidence=final_state.classification_confidence,
        classification_reason=final_state.classification_reason,
        unmapped_mentions=final_state.unmapped_mentions,
        sections=list(final_state.sections),
        synthesis_summary=synthesis.get("resumen"),
        handoff_payload=_build_handoff(ticket_id, markdown_path, synthesis),
    )


def result_to_json(result: IntakeResult) -> str:
    """Serialize an IntakeResult (used by the CLI for smoke runs)."""
    return json.dumps(asdict(result), ensure_ascii=False, indent=2)
