"""Shared LangGraph state for the dedicated ``rfp_intake`` graph.

The graph (graph.py) is intentionally separate from the CX / knowledge-agent
pipeline — the ticket requires a dedicated ``rfp_intake`` graph and forbids
hooking RFP nodes onto the existing one.
"""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from typing import Annotated, Any


@dataclass
class RFPIntakeState:
    """State flowing through classification → orchestration → synthesis."""

    #: Set by the runner before invoking the graph.
    ticket_id: str = ""
    markdown: str = ""
    metadata: dict[str, Any] = field(default_factory=dict)
    readability: dict[str, Any] = field(default_factory=dict)

    # ── classifier output ───────────────────────────────────────────────
    is_rfp: bool | None = None
    classification_confidence: float | None = None
    classification_reason: str | None = None
    #: Departments (catalog keys) the classifier believes the RFP touches.
    detected_departments: list[str] = field(default_factory=list)
    #: Mentions of departments that do NOT exist in the TrackFlow catalog.
    unmapped_mentions: list[str] = field(default_factory=list)

    # ── orchestrator output ─────────────────────────────────────────────
    #: One work item per department: {department, relevant_sections[], intent}.
    workstreams: list[dict[str, Any]] = field(default_factory=list)

    # ── worker output (parallel; appended with a reducer) ───────────────
    sections: Annotated[list[dict[str, Any]], operator.add] = field(default_factory=list)

    # ── synthesizer output ──────────────────────────────────────────────
    synthesis: dict[str, Any] | None = None

    #: Terminal error detail (shown to Ventas when the ticket is descartado).
    error: str | None = None
