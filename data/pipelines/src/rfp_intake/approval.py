"""Department-isolated human approval workflow for TrackFlow proposal sections.

Each active department runs with its own LangGraph thread. An interrupt therefore
persists and pauses only that department; peers can continue and be resumed
independently. Business conflict arbitration is deterministic and follows the
TrackFlow Hito 9 briefing.
"""
from __future__ import annotations

import asyncio
import json
import re
from datetime import datetime, timezone
from typing import Any, Callable, TypedDict

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

APPROVERS = {
    "warehouse": "Ana Whitfield",
    "lastmile": "Carlos Vega",
    "reverse": "Sofía Ramos",
}
VALID_DECISIONS = {"approve", "reject", "request_changes"}
DEFAULT_MAX_ITERATIONS = 3
COUNTRY_CURRENCY = {"us": "USD", "usa": "USD", "united states": "USD", "spain": "EUR", "españa": "EUR", "espana": "EUR"}


class ApprovalState(TypedDict, total=False):
    ticket_id: str
    department_id: str
    workstream: dict[str, Any]
    summary: str
    draft: str
    evaluation_result: dict[str, Any]
    iteration_count: int
    max_iterations: int
    approval: dict[str, Any]
    approval_status: str
    trace: list[dict[str, Any]]
    error: str
    initial_draft: str
    initial_evaluation: dict[str, Any]
    initial_iteration_count: int


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _trace(state: ApprovalState, node: str, agent: str, input_data: Any, output_data: Any) -> list[dict[str, Any]]:
    events = list(state.get("trace", []))
    events.append({
        "sequence": len(events) + 1,
        "node": node,
        "agent": agent,
        "input": input_data,
        "output": output_data,
        "timestamp": _now(),
        "ticket_id": state.get("ticket_id"),
        "department_id": state.get("department_id"),
    })
    return events


def validate_decision(value: Any) -> dict[str, str]:
    """Validate the untrusted resume payload before it can affect graph state."""
    if not isinstance(value, dict):
        raise ValueError("La decisión debe ser un objeto.")
    decision = value.get("decision")
    comment = value.get("comment", "")
    if decision not in VALID_DECISIONS:
        raise ValueError("Decisión inválida: use approve, reject o request_changes.")
    if not isinstance(comment, str) or len(comment) > 4000:
        raise ValueError("El comentario debe ser texto de hasta 4000 caracteres.")
    if decision in {"reject", "request_changes"} and not comment.strip():
        raise ValueError("El rechazo o la solicitud de cambios requiere un comentario.")
    return {"decision": decision, "comment": comment.strip()}


def _currency_for(country: Any) -> str | None:
    if not isinstance(country, str):
        return None
    return COUNTRY_CURRENCY.get(country.strip().casefold())


def arbitrate_conflicts(
    sections: list[dict[str, Any]], *, client_country: str | None, max_iterations: int = DEFAULT_MAX_ITERATIONS
) -> dict[str, Any]:
    """Return deterministic briefing-defined conflicts and required actions.

    Numeric capacity/volume and currency claims must be provided as structured
    fields. This function intentionally does not infer a capacity from prose.
    """
    active = {s.get("department_id", s.get("department")): s for s in sections}
    conflicts: list[dict[str, Any]] = []
    warehouse = active.get("warehouse") or {}
    lastmile = active.get("lastmile") or {}
    capacity = warehouse.get("committed_capacity")
    assumed_volume = lastmile.get("assumed_monthly_volume")
    if isinstance(capacity, (int, float)) and isinstance(assumed_volume, (int, float)) and assumed_volume > capacity:
        conflicts.append({
            "trigger_id": "volume-vs-capacity", "arbitrator": "Miguel Torres",
            "resolution": "Limitar el volumen de la propuesta a la capacidad de warehouse; lastmile revisa volumen/costo a la baja.",
            "affected_departments": ["warehouse", "lastmile"], "maximum_iterations": max_iterations,
        })

    for section in sections:
        department = section.get("department_id", section.get("department"))
        turnaround = section.get("returns_turnaround_hours")
        # This is structured numeric data, never an LLM-derived conflict verdict.
        if department in {"reverse", "warehouse", "lastmile"} and isinstance(turnaround, (int, float)) and turnaround < 48:
            conflicts.append({
                "trigger_id": "returns-sla-breach",
                "arbitrator": "Sofía Ramos" if department == "reverse" else "Miguel Torres",
                "resolution": "Forzar request_changes en toda sección que prometa devoluciones en menos de 48 horas.",
                "affected_departments": [department], "maximum_iterations": max_iterations,
            })

    expected_currency = _currency_for(client_country)
    currencies = {s.get("currency") for s in sections if s.get("currency")}
    offenders = {s.get("department_id", s.get("department")) for s in sections
                 if s.get("currency") and ((expected_currency and s["currency"] != expected_currency) or len(currencies) > 1)}
    if offenders:
        conflicts.append({
            "trigger_id": "currency-mismatch", "arbitrator": "Miguel Torres",
            "resolution": f"Reescribir las secciones ofensoras a {expected_currency or 'la moneda del país'}; no cerrar si persiste tras el límite.",
            "affected_departments": sorted(offenders), "maximum_iterations": max_iterations,
        })
    return {"conflicts": conflicts, "blocked": bool(conflicts)}


def build_department_approval_graph(
    *,
    checkpointer: BaseCheckpointSaver,
    generator: Callable[..., str],
    evaluator: Callable[..., dict[str, Any]],
    on_trace: Callable[[dict[str, Any]], None] | None = None,
    max_iterations: int = DEFAULT_MAX_ITERATIONS,
):
    if max_iterations < 1:
        raise ValueError("max_iterations debe ser >= 1")

    def run_node(state: ApprovalState) -> dict[str, Any]:
        department = state["department_id"]
        count = int(state.get("iteration_count", 0))
        draft = state.get("draft", "")
        evaluation = state.get("evaluation_result", {})
        approval = state.get("approval")
        if approval and approval["decision"] in {"reject", "request_changes"}:
            if count >= min(max_iterations, int(state.get("max_iterations", max_iterations))):
                result = {"approval_status": "needs_human_review", "error": "Se alcanzó el máximo de iteraciones.", "iteration_count": count}
                traced = _trace(state, "iteration_limit", "approval_guard", approval, result)
                if on_trace is not None:
                    on_trace(traced[-1])
                return {**result, "trace": traced}
            feedback = approval["comment"]
            count += 1
            draft = generator(department, state["workstream"], state.get("summary", ""), feedback)
            evaluation = evaluator(department, draft, state["workstream"].get("key_aspects") or {})
            data = {"draft": draft, "evaluation_result": evaluation, "iteration_count": count, "approval": None, "approval_status": "pending"}
            traced = _trace(state, "regenerate_section", APPROVERS[department], {"feedback": feedback, "iteration": count}, data)
            if on_trace is not None:
                on_trace(traced[-1])
            return {**data, "trace": traced}
        if count == 0 and state.get("initial_draft"):
            draft = state["initial_draft"]
            evaluation = state.get("initial_evaluation", {})
            count = max(1, int(state.get("initial_iteration_count", 1)))
        elif count == 0:
            count = 1
            draft = generator(department, state["workstream"], state.get("summary", ""), "")
            evaluation = evaluator(department, draft, state["workstream"].get("key_aspects") or {})
        data = {"draft": draft, "evaluation_result": evaluation, "iteration_count": count, "approval_status": "pending"}
        traced = _trace(state, "prepare_for_approval", f"proposal_agent:{department}", state["workstream"], data)
        if on_trace is not None:
            on_trace(traced[-1])
        return {**data, "trace": traced}

    def approval_node(state: ApprovalState) -> dict[str, Any]:
        # All content needed for an informed decision is included in the interrupt.
        payload = {
            "ticket_id": state["ticket_id"], "department_id": state["department_id"],
            "approver": APPROVERS[state["department_id"]], "draft": state.get("draft", ""),
            "evaluation_result": state.get("evaluation_result", {}),
            "key_aspects": state["workstream"].get("key_aspects", {}),
            "iteration_count": state.get("iteration_count", 0),
        }
        if on_trace is not None:
            on_trace(_trace(state, "approval_requested", APPROVERS[state["department_id"]], payload, {"status": "waiting"})[-1])
        raw = interrupt(payload)
        decision = validate_decision(raw)
        data = {"approval": decision, "approval_status": "approved" if decision["decision"] == "approve" else "changes_requested"}
        if on_trace is not None:
            on_trace(_trace(state, "human_approval", APPROVERS[state["department_id"]], payload, decision)[-1])
        return {**data, "trace": _trace(state, "human_approval", APPROVERS[state["department_id"]], payload, decision)}

    def route_after_prepare(state: ApprovalState) -> str:
        if state.get("approval_status") == "needs_human_review":
            return END
        return "approval"

    def route_after_approval(state: ApprovalState) -> str:
        decision = (state.get("approval") or {}).get("decision")
        return "prepare" if decision in {"reject", "request_changes"} else END

    builder = StateGraph(ApprovalState)
    builder.add_node("prepare", run_node)
    builder.add_node("approval", approval_node)
    builder.add_edge(START, "prepare")
    builder.add_conditional_edges("prepare", route_after_prepare)
    builder.add_conditional_edges("approval", route_after_approval)
    return builder.compile(checkpointer=checkpointer)


def department_thread_id(ticket_id: str, department_id: str) -> str:
    if not ticket_id or department_id not in APPROVERS:
        raise ValueError("ticket_id y department_id activo son obligatorios")
    return f"rfp-{ticket_id}:{department_id}"


def invoke_department_approval(graph: Any, *, ticket_id: str, department_id: str,
                               workstream: dict[str, Any], summary: str,
                               generator: Callable[..., str], evaluator: Callable[..., dict[str, Any]],
                               max_iterations: int = DEFAULT_MAX_ITERATIONS,
                               resume: dict[str, Any] | None = None,
                               initial_draft: str = "",
                               initial_evaluation: dict[str, Any] | None = None,
                               initial_iteration_count: int = 0,
                               on_trace: Callable[[dict[str, Any]], None] | None = None) -> dict[str, Any]:
    """Start or resume one department thread; never starts other ticket phases."""
    config = {"configurable": {"thread_id": department_thread_id(ticket_id, department_id)}}
    if resume is not None:
        decision = validate_decision(resume)
        result = graph.invoke(Command(resume=decision), config=config)
    else:
        result = graph.invoke({
            "ticket_id": ticket_id, "department_id": department_id,
            "workstream": workstream, "summary": summary,
            "max_iterations": max_iterations,
            "iteration_count": 0,
            "initial_draft": initial_draft,
            "initial_evaluation": initial_evaluation or {},
            "initial_iteration_count": initial_iteration_count,
        }, config=config)
    return result