from __future__ import annotations

import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
PIPELINES_SRC = ROOT / "data" / "pipelines" / "src"
if str(PIPELINES_SRC) not in sys.path:
    sys.path.insert(0, str(PIPELINES_SRC))

from rfp_intake import proposal


GOOD_SECTION = """Alcance: almacenamiento e integración de inventario para 15.000 SKUs en Zaragoza.
Entregables: API de inventario unificada, alertas de stock bajo y dashboard de operaciones.
Consideraciones económicas: tarifa estándar según volumen ocupado; precio final pendiente de confirmar.
Supuestos: el cliente facilitará sus datos maestros y volúmenes mensuales.
Datos pendientes: confirmar volumen mensual de pedidos."""


def test_department_generators_are_distinct_and_scoped():
    assert len(proposal.DEPARTMENT_GENERATORS) == 7
    assert proposal.DEPARTMENT_GENERATORS["tecnologia"] is not proposal.DEPARTMENT_GENERATORS["comercial_cuentas"]
    try:
        proposal.DEPARTMENT_GENERATORS["tecnologia"].generate(
            {"department": "comercial_cuentas", "key_aspects": {}}
        )
    except ValueError as exc:
        assert "no puede procesar" in str(exc)
    else:
        raise AssertionError("cross-department generation must be rejected")


def test_structured_evaluation_success(monkeypatch):
    monkeypatch.setattr(proposal, "chat_json", lambda **kwargs: {"section_text": GOOD_SECTION})
    workstream = {
        "department": "operaciones_almacen",
        "key_aspects": {
            "resumen_requisitos": "API unificada para inventario de SKUs",
            "entregables": ["API de inventario unificada", "dashboard de operaciones"],
            "cifras_citadas": [{"valor": "15.000 SKUs", "contexto": "alcance"}],
        },
    }
    draft = proposal.generate_department_section("operaciones_almacen", workstream, "Resumen RFP")
    result = proposal.evaluate_section("operaciones_almacen", draft, workstream["key_aspects"])
    assert "15.000 SKUs" in draft
    assert result["overall_pass"] is True
    assert set(result) == {
        "section_id", "department_id", "readability", "relevance", "compliance",
        "overall_pass", "feedback_for_generator",
    }


def test_evaluation_failure_returns_actionable_feedback():
    aspects = {"entregables": ["integración de tracking unificado", "portal de seguimiento público"]}
    result = proposal.evaluate_section("ultima_milla_transportistas", "Texto corto.", aspects)
    assert result["overall_pass"] is False
    assert result["readability"]["pass"] is False
    assert result["relevance"]["missing_aspects"]
    assert "legibilidad" in result["feedback_for_generator"].lower()


def test_compliance_failure_anchored_to_trackflow_rule():
    draft = "TrackFlow garantizará entrega express internacional en 24 horas en cualquier zona."
    result = proposal.evaluate_section("ultima_milla_transportistas", draft, {})
    assert result["compliance"]["pass"] is False
    assert "SLA-01" in result["compliance"]["rule_ids"]
    assert result["compliance"]["violations"]


def test_failed_cycle_keeps_last_draft_and_human_review():
    calls = []

    def generator(department, workstream, summary, feedback):
        calls.append(feedback)
        return "No cumple el requisito de inventario." if len(calls) == 1 else "Sigue sin detalles suficientes."

    updates = []
    result = asyncio.run(proposal.run_section_cycle(
        {"department": "operaciones_almacen", "key_aspects": {"entregables": ["API de inventario unificada"]}},
        "resumen", max_iterations=2, generator=generator, on_update=updates.append,
    ))
    assert result["status"] == "needs_human_review"
    assert result["draft"] == "Sigue sin detalles suficientes."
    assert result["evaluation_result"]["overall_pass"] is False
    assert result["iteration_count"] == 2
    assert calls[1]
    assert updates[-1]["status"] == "needs_human_review"


def test_handoff_runs_departments_independently_and_preserves_failed_section():
    def generator(department, workstream, summary, feedback):
        if department == "logistica_inversa":
            return "TrackFlow reacondicionará y revenderá los productos devueltos."
        return GOOD_SECTION

    handoff = {
        "ticket_id": "t-42",
        "synthesizer_summary": "Resumen del synthesizer",
        "workstreams": [
            {"department": "operaciones_almacen", "key_aspects": {"entregables": ["API de inventario unificada"]}},
            {"department": "logistica_inversa", "key_aspects": {"entregables": ["gestión de devoluciones"]}},
        ],
    }
    result = asyncio.run(proposal.run_proposal_handoff(handoff, max_iterations=1, generator=generator))
    assert len(result["proposal_sections"]) == 2
    failed = next(s for s in result["proposal_sections"] if s["department"] == "logistica_inversa")
    assert failed["status"] == "needs_human_review"
    assert "RETURNS-02" in failed["evaluation_result"]["compliance"]["rule_ids"]
    assert result["needs_human_review"] is True
