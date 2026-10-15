"""Runner-level tests for rfp_intake (graph nodes mocked, no network, no DB).

Covered here:
  * ConversionError (missing / unreadable PDF) → ``status='descartado'``.
  * Classifier rejection → ``descartado`` preserving the reason.
  * Low-confidence rejection → ``descartado`` + human-review annotation.
  * Acceptance → ``analisis_completo`` + Parte 2 handoff payload shape.

Run::

    cd data/pipelines
    uv run pytest ../../tests/pipelines/test_rfp_intake_runner.py -v
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

_ROOT = Path(__file__).resolve().parents[2]
_SRC = _ROOT / "data" / "pipelines" / "src"
if str(_SRC) not in sys.path:
    sys.path.insert(0, str(_SRC))

from rfp_intake import graph as graph_module  # noqa: E402
from rfp_intake import runner  # noqa: E402
from rfp_intake.agents.classifier import ClassifierDecision  # noqa: E402
from rfp_intake.conversion import ConversionError  # noqa: E402

_MD_TEXT = "REQUEST FOR PROPOSAL (RFP) Ref MV-LOG-2026-03: fulfilment for 15.000 SKUs near Zaragoza."


class _FakeConversion:
    def __init__(self, markdown_path: Path):
        self.markdown_path = markdown_path


@pytest.fixture
def fake_convert(monkeypatch):
    """Replace MarkItDown conversion with a stub that emits a .md file."""

    def _convert(pdf_path, output_dir):
        output_dir = Path(output_dir)
        output_dir.mkdir(parents=True, exist_ok=True)
        markdown_path = output_dir / f"{Path(pdf_path).stem}.md"
        markdown_path.write_text(_MD_TEXT, encoding="utf-8")
        return _FakeConversion(markdown_path)

    monkeypatch.setattr(runner, "convert_pdf_to_markdown", _convert)
    return _convert


def _pdf(tmp_path) -> Path:
    pdf = tmp_path / "sample.pdf"
    pdf.write_bytes(b"%PDF-1.4 fake")  # content irrelevant: conversion is mocked
    return pdf


def test_runner_descarta_on_conversion_error(tmp_path, monkeypatch):
    def _broken(pdf_path, output_dir):
        raise ConversionError("PDF escaneado o ilegible")

    monkeypatch.setattr(runner, "convert_pdf_to_markdown", _broken)

    result = runner.run_pipeline("t-1", _pdf(tmp_path), tmp_path / "artifacts")

    assert result.status == runner.STATUS_DESCARTADO
    assert result.handoff_payload is None
    assert "escaneado" in result.error_detail


def test_runner_descarta_when_classifier_rejects(tmp_path, fake_convert, monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=False,
            confidence=0.93,
            reason="Oferta comercial de un proveedor dirigida a TrackFlow.",
            detected_departments=[],
            unmapped_mentions=[],
        ),
    )

    result = runner.run_pipeline("t-2", _pdf(tmp_path), tmp_path / "artifacts")

    assert result.status == runner.STATUS_DESCARTADO
    assert result.is_rfp is False
    assert "proveedor" in result.classification_reason
    assert result.markdown_path is not None  # artifact kept for audit


def test_runner_low_confidence_rejection_flags_human_review(tmp_path, fake_convert, monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=False,
            confidence=0.35,
            reason="Documento ambiguo.",
            detected_departments=[],
            unmapped_mentions=[],
        ),
    )

    result = runner.run_pipeline("t-3", _pdf(tmp_path), tmp_path / "artifacts")

    assert result.status == runner.STATUS_DESCARTADO
    assert "REVISION HUMANA RECOMENDADA" in result.error_detail


def test_runner_acceptance_builds_handoff_payload(tmp_path, fake_convert, monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=True,
            confidence=0.96,
            reason="RFP formal.",
            detected_departments=["operaciones_almacen", "tecnologia"],
            unmapped_mentions=[],
        ),
    )
    monkeypatch.setattr(
        graph_module,
        "plan_workstreams",
        lambda markdown, metadata, detected_departments: [
            {
                "department": department,
                "prioridad": "alta",
                "intencion": "prep",
                "extractos": ["15.000 SKUs"],
                "contact_name": "x",
                "contact_role": "y",
            }
            for department in detected_departments
        ],
    )
    monkeypatch.setattr(
        graph_module,
        "process_workstream",
        lambda workstream, metadata: {
            "department": workstream["department"],
            "contact_name": workstream["department"],
            "contact_role": "rol",
            "status": "completado",
            "worker_error": None,
            "key_aspects": {"resumen_requisitos": "15.000 SKUs", "missing_data": []},
        },
    )
    monkeypatch.setattr(
        graph_module,
        "synthesize_sections",
        lambda sections, metadata: {
            "resumen": "Resumen para Ventas.",
            "contradicciones": [],
            "handoff": [
                {
                    "department": section["department"],
                    "contact_name": section["contact_name"],
                    "contact_role": section["contact_role"],
                    "key_aspects": section["key_aspects"],
                }
                for section in sections
            ],
        },
    )

    result = runner.run_pipeline("t-4", _pdf(tmp_path), tmp_path / "artifacts")

    assert result.status == runner.STATUS_ANALISIS_COMPLETO
    assert result.is_rfp is True
    # Both parallel workers produced their sections (Send fan-out executed).
    assert sorted(s["department"] for s in result.sections) == [
        "operaciones_almacen",
        "tecnologia",
    ]

    handoff = result.handoff_payload
    assert set(handoff) == {
        "ticket_id",
        "markdown_path",
        "workstreams",
        "synthesizer_summary",
        "contradicciones",
    }
    assert handoff["ticket_id"] == "t-4"
    assert handoff["synthesizer_summary"] == "Resumen para Ventas."
    assert len(handoff["workstreams"]) == 2
    # Handoff is JSON-serializable (it is persisted as JSON text).
    json.dumps(handoff)


def test_result_to_json_is_serializable(tmp_path, fake_convert, monkeypatch):
    monkeypatch.setattr(
        graph_module,
        "classify_document",
        lambda markdown, metadata: ClassifierDecision(
            is_rfp=False,
            confidence=0.9,
            reason="no",
            detected_departments=[],
            unmapped_mentions=[],
        ),
    )

    result = runner.run_pipeline("t-5", _pdf(tmp_path), tmp_path / "artifacts")
    payload = json.loads(runner.result_to_json(result))

    assert payload["ticket_id"] == "t-5"
    assert payload["status"] == runner.STATUS_DESCARTADO
