"""End-to-end, fully synthetic RFP approval example (no LLM or database)."""
from __future__ import annotations

import json
from pathlib import Path

from langgraph.checkpoint.memory import InMemorySaver

from rfp_intake.approval import (
    APPROVERS,
    build_department_approval_graph,
    invoke_department_approval,
)


RFP_INPUT = {
    "ticket_id": "demo-rfp-2026-001",
    "client": "Luna Cosmetics (cuenta ficticia)",
    "country": "España",
    "summary": "Solicitamos almacenamiento, entrega nacional y gestión de devoluciones para 1.200 pedidos mensuales.",
    "workstreams": {
        "warehouse": {
            "department": "warehouse",
            "key_aspects": {"capacity": "1.500 pedidos mensuales", "location": "Madrid"},
            "committed_capacity": 1500,
            "currency": "EUR",
        },
        "lastmile": {
            "department": "lastmile",
            "key_aspects": {"coverage": "España peninsular", "volume": "1.200 pedidos mensuales"},
            "assumed_monthly_volume": 1200,
            "currency": "EUR",
        },
        "reverse": {
            "department": "reverse",
            "key_aspects": {"returns": "Inspección y reintegro en 72 horas"},
            "returns_turnaround_hours": 72,
            "currency": "EUR",
        },
    },
}


def _synthetic_generator(department: str, workstream: dict, summary: str, feedback: str) -> str:
    """Return deterministic fixture prose; intentionally makes no model/API calls."""
    aspect_lines = "\n".join(f"- {key}: {value}" for key, value in workstream["key_aspects"].items())
    revision = f"\nAjuste solicitado: {feedback}" if feedback else ""
    return f"Sección {department} para {workstream['department']}.\n{summary}\n{aspect_lines}{revision}"


def _synthetic_evaluator(department: str, draft: str, aspects: dict) -> dict:
    """Fixture evaluator used to exercise the approval workflow without an LLM."""
    return {"overall_pass": True, "department_id": department, "checked_aspects": list(aspects), "source": "synthetic-demo"}


def _render_final_document(rfp: dict, approved: dict[str, dict]) -> str:
    sections = [
        f"# Propuesta logística — {rfp['client']}",
        f"**Ticket:** {rfp['ticket_id']}  \n**País:** {rfp['country']}",
        f"\n## Solicitud\n{rfp['summary']}",
        "\n## Alcance aprobado",
    ]
    for department in ("warehouse", "lastmile", "reverse"):
        decision = approved[department]["approval"]
        sections.append(
            f"\n### {department.title()} — aprobado por {APPROVERS[department]}\n"
            f"{approved[department]['draft']}\n\nDecisión: {decision['decision']}"
        )
    sections.append("\n---\nDocumento de demostración; datos y aprobaciones completamente ficticios.")
    return "\n".join(sections)


def run_demo() -> tuple[dict[str, dict], str, list[dict]]:
    """Run the actual interrupt/resume graph independently for each department."""
    trace_events: list[dict] = []
    graph = build_department_approval_graph(
        checkpointer=InMemorySaver(),
        generator=_synthetic_generator,
        evaluator=_synthetic_evaluator,
        on_trace=trace_events.append,
    )
    approved: dict[str, dict] = {}
    for department, workstream in RFP_INPUT["workstreams"].items():
        waiting = invoke_department_approval(
            graph,
            ticket_id=RFP_INPUT["ticket_id"],
            department_id=department,
            workstream=workstream,
            summary=RFP_INPUT["summary"],
            generator=_synthetic_generator,
            evaluator=_synthetic_evaluator,
            initial_draft=_synthetic_generator(department, workstream, RFP_INPUT["summary"], ""),
            initial_evaluation=_synthetic_evaluator(department, "synthetic draft", workstream["key_aspects"]),
            initial_iteration_count=1,
        )
        assert waiting["__interrupt__"][0].value["department_id"] == department
        approved[department] = invoke_department_approval(
            graph,
            ticket_id=RFP_INPUT["ticket_id"],
            department_id=department,
            workstream=workstream,
            summary=RFP_INPUT["summary"],
            generator=_synthetic_generator,
            evaluator=_synthetic_evaluator,
            resume={"decision": "approve", "comment": "Aprobación simulada para la demo."},
        )
        assert approved[department]["approval_status"] == "approved"

    document = _render_final_document(RFP_INPUT, approved)
    return approved, document, trace_events


def test_synthetic_rfp_all_departments_approve_and_final_document_is_generated():
    approved, document, traces = run_demo()

    assert list(approved) == ["warehouse", "lastmile", "reverse"]
    assert all(result["approval"]["decision"] == "approve" for result in approved.values())
    assert {event["node"] for event in traces} >= {
        "prepare_for_approval", "approval_requested", "human_approval"
    }
    assert all(event["ticket_id"] == RFP_INPUT["ticket_id"] for event in traces)
    assert "1.500 pedidos mensuales" in document
    assert "Inspección y reintegro en 72 horas" in document
    assert "Documento de demostración" in document


if __name__ == "__main__":
    decisions, final_document, events = run_demo()
    print("RFP DE ENTRADA")
    print(json.dumps(RFP_INPUT, ensure_ascii=False, indent=2))
    print("\nAPROBACIONES SIMULADAS")
    print(json.dumps({dept: {"approver": APPROVERS[dept], "decision": state["approval"]}
                      for dept, state in decisions.items()}, ensure_ascii=False, indent=2))
    print(f"\nEVENTOS DE TRAZA: {len(events)}")
    print("\nDOCUMENTO FINAL GENERADO\n")
    print(final_document)