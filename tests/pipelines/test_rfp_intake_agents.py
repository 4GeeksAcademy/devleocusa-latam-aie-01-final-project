"""Unit tests for the rfp_intake agents (LLM mocked — no network).

Run from the pipelines project::

    cd data/pipelines
    uv run pytest ../../tests/pipelines/test_rfp_intake_agents.py -v

Each test monkey-patches the per-module ``chat_json`` binding (the agents
import it by name), so no LLM endpoint is ever contacted.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "data" / "pipelines" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from langgraph.graph import END  # noqa: E402

from rfp_intake import graph as graph_module  # noqa: E402
from rfp_intake.agents import (  # noqa: E402
    classifier,
    orchestrator,
    synthesizer,
    worker,
)
from rfp_intake.agents.classifier import ClassifierDecision  # noqa: E402
from rfp_intake.agents.llm import LLMResponseError  # noqa: E402
from rfp_intake.config import LOW_CONFIDENCE_THRESHOLD  # noqa: E402
from rfp_intake.state import RFPIntakeState  # noqa: E402

FORMAL_MD = """REQUEST FOR PROPOSAL (RFP)
Ref: MV-LOG-2026-03 — ModaViva, S.L.
Scope: fulfilment for 15.000 SKUs near Zaragoza, returns and ERP API integration.
Due: August 28, 2026. Contact: Elena Bosch, logistica@modaviva.es.
"""

VENDOR_MD = """Hi TrackFlow team,
We offer introductory carrier rates for last-mile in Spain. Let's talk?
Jake Fenwick, RapidShip
"""


def _fake_llm_factory(payloads):
    """chat_json stand-in returning queued payloads (last one repeats)."""
    calls = {"n": 0}

    def fake_chat_json(**kwargs):
        index = min(calls["n"], len(payloads) - 1)
        calls["n"] += 1
        item = payloads[index]
        if isinstance(item, Exception):
            raise item
        return item

    fake_chat_json.calls = calls
    return fake_chat_json


# ─────────────────────────────────────────────────────────────────────
# Classifier
# ─────────────────────────────────────────────────────────────────────


def test_classifier_accepts_formal_rfp(monkeypatch):
    monkeypatch.setattr(
        classifier,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "is_rfp": True,
                    "confidence": 0.96,
                    "reason": "RFP formal con alcance, cifras y fecha de entrega de propuesta.",
                    "detected_departments": [
                        "operaciones_almacen",
                        "logistica_inversa",
                        "tecnologia",
                        "gestion_de_remates",
                    ],
                }
            ]
        ),
    )

    decision = classifier.classify_document(FORMAL_MD, {"title": "REQUEST FOR PROPOSAL"})

    assert decision.is_rfp is True
    assert decision.confidence == pytest.approx(0.96)
    # Catalog-only departments are mapped; unknown mentions are surfaced.
    assert decision.detected_departments == [
        "operaciones_almacen",
        "logistica_inversa",
        "tecnologia",
    ]
    assert decision.unmapped_mentions == ["gestion_de_remates"]


def test_classifier_rejects_vendor_pitch_and_coerces_strings(monkeypatch):
    monkeypatch.setattr(
        classifier,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "is_rfp": "false",
                    "confidence": 0.93,
                    "reason": "Oferta comercial de un proveedor dirigida a TrackFlow; no es una solicitud.",
                    "detected_departments": [],
                }
            ]
        ),
    )

    decision = classifier.classify_document(VENDOR_MD, {})

    assert decision.is_rfp is False
    assert decision.confidence == pytest.approx(0.93)
    assert decision.detected_departments == []


def test_classifier_normalizes_department_names(monkeypatch):
    monkeypatch.setattr(
        classifier,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "is_rfp": True,
                    "confidence": 0.9,
                    "reason": "ok",
                    "detected_departments": [
                        "Operaciones Almacen",
                        "operaciones_almacen",
                        "ultima_milla-transportistas",
                        "",
                    ],
                }
            ]
        ),
    )

    decision = classifier.classify_document(FORMAL_MD, {})

    assert decision.detected_departments == [
        "operaciones_almacen",
        "ultima_milla_transportistas",
    ]
    assert decision.unmapped_mentions == []


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("alta", 0.5), (1.7, 1.0), ("0.9", 0.9), (None, 0.5), (2, 1.0)],
)
def test_classifier_coerces_confidence(raw, expected, monkeypatch):
    monkeypatch.setattr(
        classifier,
        "chat_json",
        _fake_llm_factory([{"is_rfp": True, "confidence": raw, "reason": "ok"}]),
    )
    decision = classifier.classify_document(FORMAL_MD, {})
    assert decision.confidence == pytest.approx(expected)


# ─────────────────────────────────────────────────────────────────────
# Worker
# ─────────────────────────────────────────────────────────────────────


def _workstream(department: str = "operaciones_almacen"):
    return {
        "department": department,
        "prioridad": "alta",
        "intencion": "Preparar la operacion de almacen para el RFP de ModaViva",
        "extractos": ["Scope: fulfilment for 15.000 SKUs near Zaragoza"],
    }


def test_worker_copies_literal_figures_and_flags_missing_data(monkeypatch):
    monkeypatch.setattr(
        worker,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "resumen_requisitos": "Preparar 15.000 SKUs cerca de Zaragoza con devoluciones.",
                    "entregables": ["Plan de slots de recepcion"],
                    "cifras_citadas": [
                        {"valor": "15.000 SKUs", "contexto": "alcance, seccion 2"}
                    ],
                    "restricciones_exclusiones": ["No se requiere gestion de transportistas"],
                    "preguntas_abiertas": ["¿Volumen mensual de pedidos?"],
                    "missing_data": ["Volumen mensual de pedidos"],
                    "prioridad": "alta",
                }
            ]
        ),
    )

    section = worker.process_workstream(_workstream(), {"title": "RFP"})

    assert section["status"] == "completado"
    assert section["worker_error"] is None
    assert section["contact_name"] == "Ana Whitfield"
    assert section["contact_role"] == "Directora de Operaciones de Almacén"
    aspects = section["key_aspects"]
    # Literal figures must be copied verbatim — never recomputed or invented.
    assert aspects["cifras_citadas"][0]["valor"] == "15.000 SKUs"
    assert aspects["missing_data"] == ["Volumen mensual de pedidos"]


def test_worker_retries_then_succeeds(monkeypatch):
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        worker,
        "chat_json",
        _fake_llm_factory(
            [
                LLMResponseError("JSON invalido (intento 1)"),
                {"resumen_requisitos": "ok", "missing_data": []},
            ]
        ),
    )

    section = worker.process_workstream(_workstream(), {})

    assert section["status"] == "completado"
    assert worker.chat_json.calls["n"] == 2


def test_worker_never_raises_and_marks_error(monkeypatch):
    monkeypatch.setattr(worker.time, "sleep", lambda *_: None)
    monkeypatch.setattr(
        worker,
        "chat_json",
        _fake_llm_factory([LLMResponseError("endpoint caido")]),
    )

    # Must NOT raise: a broken worker degrades to status='error' so the
    # remaining departments still get their sections.
    section = worker.process_workstream(_workstream("tecnologia"), {})

    assert section["status"] == "error"
    assert section["key_aspects"] is None
    assert "intentos" in section["worker_error"]
    assert section["contact_name"] == "Andrés Kim"


# ─────────────────────────────────────────────────────────────────────
# Orchestrator
# ─────────────────────────────────────────────────────────────────────


def test_orchestrator_filters_unknown_dedups_and_coerces(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "workstreams": [
                        {
                            "department": "operaciones_almacen",
                            "prioridad": "ALTA",
                            "intencion": "ops",
                            "extractos": ["x" * 2000, 42, "  "],
                        },
                        {"department": "operaciones_almacen", "intencion": "dup"},
                        {"department": "no_existe", "intencion": "junk"},
                        {
                            "department": "tecnologia",
                            "prioridad": "urgente",
                            "intencion": "tech",
                            "extractos": ["api"],
                        },
                    ]
                }
            ]
        ),
    )

    workstreams = orchestrator.plan_workstreams(FORMAL_MD, {}, ["operaciones_almacen", "tecnologia"])

    # Unknown department dropped; duplicates merged.
    assert [w["department"] for w in workstreams] == ["operaciones_almacen", "tecnologia"]
    ops = workstreams[0]
    assert ops["prioridad"] == "alta"
    assert len(ops["extractos"]) == 1  # int + whitespace dropped
    assert len(ops["extractos"][0]) == 1600  # verbatim excerpts are capped
    # Invalid prioridad falls back to 'media'; contacts come from the catalog.
    assert workstreams[1]["prioridad"] == "media"
    assert workstreams[1]["contact_name"] == "Andrés Kim"


def test_orchestrator_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        orchestrator,
        "chat_json",
        _fake_llm_factory([RuntimeError("sin red")]),
    )

    workstreams = orchestrator.plan_workstreams(FORMAL_MD, {}, ["logistica_inversa"])

    assert len(workstreams) == 1
    assert workstreams[0]["department"] == "logistica_inversa"
    assert workstreams[0]["contact_name"] == "Sofía Ramos"


# ─────────────────────────────────────────────────────────────────────
# Synthesizer
# ─────────────────────────────────────────────────────────────────────


def _sections():
    return [
        {
            "department": "operaciones_almacen",
            "contact_name": "Ana Whitfield",
            "contact_role": "Directora de Operaciones de Almacen",
            "status": "completado",
            "worker_error": None,
            "key_aspects": {"resumen_requisitos": "15.000 SKUs", "missing_data": []},
        }
    ]


def test_synthesizer_normalizes_output(monkeypatch):
    monkeypatch.setattr(
        synthesizer,
        "chat_json",
        _fake_llm_factory(
            [
                {
                    "resumen": "Resumen para Ventas.",
                    "contradicciones": [
                        {"tema": "volumen", "version_a": "5.000", "version_b": "10.000"}
                    ],
                    "handoff": [
                        {
                            "department": "operaciones_almacen",
                            "contact_name": "Ana Whitfield",
                            "contact_role": "Directora de Operaciones de Almacen",
                            "key_aspects": {"resumen_requisitos": "15.000 SKUs"},
                        },
                        "garbage",
                    ],
                }
            ]
        ),
    )

    synthesis = synthesizer.synthesize_sections(_sections(), {})

    assert synthesis["resumen"] == "Resumen para Ventas."
    # Contradictions are surfaced, never silently merged (D4).
    assert synthesis["contradicciones"][0]["tema"] == "volumen"
    assert len(synthesis["handoff"]) == 1  # non-dict entries dropped
    assert synthesis["handoff"][0]["key_aspects"] == {"resumen_requisitos": "15.000 SKUs"}


def test_synthesizer_falls_back_when_llm_fails(monkeypatch):
    monkeypatch.setattr(
        synthesizer,
        "chat_json",
        _fake_llm_factory([RuntimeError("timeout")]),
    )

    synthesis = synthesizer.synthesize_sections(_sections(), {})

    assert synthesis["resumen"]
    assert [h["department"] for h in synthesis["handoff"]] == ["operaciones_almacen"]


# ─────────────────────────────────────────────────────────────────────
# Graph routing
# ─────────────────────────────────────────────────────────────────────


def _state(**kwargs):
    defaults = {"ticket_id": "t-1", "markdown": "md", "metadata": {}, "readability": {}}
    defaults.update(kwargs)
    return RFPIntakeState(**defaults)


def test_route_valid_rfp_to_orchestrator():
    state = _state(is_rfp=True, classification_confidence=0.95, classification_reason="ok")
    assert graph_module.route_after_classification(state) == "orchestrator"


def test_route_rejection_ends_graph():
    state = _state(is_rfp=False, classification_confidence=0.93, classification_reason="pitch")
    assert graph_module.route_after_classification(state) == END


def test_classifier_node_annotates_low_confidence_rejection(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=False,
            confidence=0.3,
            reason="documento ambiguo",
            detected_departments=[],
            unmapped_mentions=[],
        ),
    )

    update = graph_module._classifier_node(_state())

    # False negatives must not disappear silently (D3). The annotation is a
    # state UPDATE: LangGraph does not propagate mutations from routers.
    assert "REVISION HUMANA RECOMENDADA" in update["error"]
    assert str(LOW_CONFIDENCE_THRESHOLD) in update["error"]


def test_classifier_node_leaves_error_none_on_confident_rejection(monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=False,
            confidence=0.93,
            reason="pitch",
            detected_departments=[],
            unmapped_mentions=[],
        ),
    )

    update = graph_module._classifier_node(_state())

    assert update["error"] is None
