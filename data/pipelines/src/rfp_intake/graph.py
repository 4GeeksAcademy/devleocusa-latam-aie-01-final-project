"""The dedicated ``rfp_intake`` LangGraph graph.

Flow::

    START → classifier ─(no es RFP)→ END              (ticket → descartado)
                  │
                  └─(es RFP)→ orchestrator ─Send─→ worker (N en paralelo)
                                                              │
                                              synthesizer ←───┘  (espera a todos)
                                                     │
                                                    END          (analisis_completo)

This graph is intentionally NOT wired to the CX / knowledge-agent pipeline.
Routers in services/ trigger it through runner.run_pipeline() only.
"""

from __future__ import annotations

from typing import Any

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send

from .config import LOW_CONFIDENCE_THRESHOLD
from .state import RFPIntakeState
from .agents.classifier import classify_document
from .agents.orchestrator import plan_workstreams
from .agents.synthesizer import synthesize_sections
from .agents.worker import process_workstream


def _classifier_node(
    state: RFPIntakeState, on_classified: Any = None
) -> dict[str, Any]:
    decision = classify_document(state.markdown, state.metadata)
    if decision.is_rfp and on_classified is not None:
        on_classified(
            state.ticket_id, state.metadata, list(decision.detected_departments)
        )
    error = None
    if not decision.is_rfp and decision.confidence < LOW_CONFIDENCE_THRESHOLD:
        # D3 — false negatives must not disappear silently: annotate the
        # rejection so Ventas knows a human review is advised. The annotation
        # is emitted as a STATE UPDATE here (not in the router): LangGraph
        # does not propagate mutations made inside routing functions.
        error = (
            f"[REVISION HUMANA RECOMENDADA — confianza "
            f"{decision.confidence:.2f} < {LOW_CONFIDENCE_THRESHOLD}] "
            f"{decision.reason}"
        )
    return {
        "is_rfp": decision.is_rfp,
        "classification_confidence": decision.confidence,
        "classification_reason": decision.reason,
        "detected_departments": decision.detected_departments,
        "unmapped_mentions": decision.unmapped_mentions,
        "error": error,
    }


def route_after_classification(state: RFPIntakeState) -> str:
    """Valid RFP → orchestrator; anything else → END (ticket becomes descartado).

    A rejection with confidence below the threshold is still terminal, but its
    reason is annotated so Ventas knows a human review is advised (D3 — false
    negatives must not disappear silently).
    """
    if state.is_rfp:
        return "orchestrator"
    return END


def _orchestrator_node(state: RFPIntakeState) -> dict[str, Any]:
    workstreams = plan_workstreams(
        markdown=state.markdown,
        metadata=state.metadata,
        detected_departments=state.detected_departments,
    )
    return {"workstreams": workstreams}


def _fan_out_workers(state: RFPIntakeState) -> list[Send]:
    """One parallel worker per department workstream (orchestrator-worker pattern)."""
    return [
        Send(
            "worker",
            {
                "workstream": workstream,
                "metadata": state.metadata,
            },
        )
        for workstream in state.workstreams
    ]


def _worker_node(payload: dict[str, Any]) -> dict[str, Any]:
    section = process_workstream(
        workstream=payload["workstream"],
        metadata=payload.get("metadata"),
    )
    return {"sections": [section]}


def _synthesizer_node(state: RFPIntakeState) -> dict[str, Any]:
    synthesis = synthesize_sections(sections=state.sections, metadata=state.metadata)
    return {"synthesis": synthesis}


def build_graph(*, on_classified: Any = None):
    """Compose and return the compiled rfp_intake graph."""
    graph = StateGraph(RFPIntakeState)

    graph.add_node(
        "classifier",
        lambda state: _classifier_node(state, on_classified=on_classified),
    )
    graph.add_node("orchestrator", _orchestrator_node)
    graph.add_node("worker", _worker_node)
    graph.add_node("synthesizer", _synthesizer_node)

    graph.add_edge(START, "classifier")
    graph.add_conditional_edges(
        "classifier",
        route_after_classification,
        {"orchestrator": "orchestrator", END: END},
    )
    # Fan-out: the orchestrator emits one Send per workstream.
    graph.add_conditional_edges("orchestrator", _fan_out_workers, ["worker"])
    # LangGraph waits for every parallel branch before the next superstep, so
    # the synthesizer runs exactly once, after ALL workers have finished.
    graph.add_edge("worker", "synthesizer")
    graph.add_edge("synthesizer", END)

    return graph.compile()
