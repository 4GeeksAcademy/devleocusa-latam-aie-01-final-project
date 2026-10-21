"""Parte 2: department-specific proposal drafting and structured evaluation.

This module consumes only the Part 1 synthesizer handoff. Each department has
its own generator instance and scoped instructions; evaluations are isolated
and combined by the orchestrator after running concurrently.
"""
from __future__ import annotations

import asyncio
import re
from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
from typing import Any, Callable

from .agents.llm import chat_json

MAX_ITERATIONS = 3

DEPARTMENT_INSTRUCTIONS: dict[str, str] = {
    "warehouse": "Redacta capacidad de almacenamiento, costo por pallet/SKU y tiempo de onboarding. Usa la moneda del cliente.",
    "lastmile": "Redacta costo por envío, transportistas disponibles según destino y SLA de entrega. No reveles tarifas negociadas de carriers.",
    "reverse": "Redacta costo y tiempo de procesamiento de devoluciones; nunca prometas turnaround inferior a 48 horas.",
    "operaciones_almacen": "Redacta la sección de almacenaje, recepción, inventario, picking, packing e integración de pedidos.",
    "ultima_milla_transportistas": "Redacta la sección de transporte, selección de carrier, tracking y entregas.",
    "logistica_inversa": "Redacta la sección de devoluciones, inspección, etiquetas y logística inversa.",
    "experiencia_cliente": "Redacta la sección de atención B2B/B2C, tickets, consultas y base de conocimiento.",
    "comercial_cuentas": "Redacta la sección de alcance comercial, estructura económica y gestión de cuenta.",
    "tecnologia": "Redacta la sección de integraciones, APIs, telemetría, datos, seguridad y viabilidad técnica.",
    "direccion_ejecutiva": "Redacta la sección de encaje estratégico, riesgos, supuestos y visión ejecutiva.",
}

# Rules are anchored to the internal TrackFlow briefing and knowledge base.
COMPLIANCE_RULES: tuple[dict[str, Any], ...] = (
    {"id": "SLA-01", "text": "No garantizar entregas internacionales ni plazos de aduana; internacional US-España requiere 7-12 días hábiles y está sujeto a aduana.", "patterns": (r"garantiz\w*.{0,50}(?:aduana|internacional)", r"aduana.{0,50}garantiz\w*", r"internacional.{0,60}24\s*horas")},
    {"id": "SLA-02", "text": "Express 24-48h solo en zonas metropolitanas de Los Ángeles y Zaragoza-Madrid.", "patterns": (r"express.{0,80}(?:cualquier|toda|todo)\s+(?:zona|destino|pa[ií]s)", r"24\s*(?:a|-)\s*48\s*h.{0,60}(?:cualquier|toda)\s+(?:zona|destino)")},
    {"id": "SLA-03", "text": "No garantizar SLA durante Black Friday, Navidad o Rebajas de enero; los plazos pueden extenderse hasta 40%.", "patterns": (r"garantiz\w*.{0,80}(?:black friday|navidad|rebajas)", r"(?:black friday|navidad|rebajas).{0,80}garantiz\w*")},
    {"id": "STORAGE-01", "text": "Los descuentos de almacenamiento sobre 50 m³ deben negociarse con Miguel Torres; no ofrecerlos unilateralmente.", "patterns": (r"(?:descuento|rebaja|tarifa preferencial).{0,80}(?:almacen|storage).{0,80}(?:autom[aá]tic|garantiz|sin aprobaci)", r"(?:almacen|storage).{0,80}(?:descuento|rebaja).{0,80}sin (?:aprobaci|negociaci)")},
    {"id": "RETURNS-01", "text": "Devoluciones internacionales requieren gestión manual; no presentarlas como proceso automático estándar.", "patterns": (r"devoluci[oó]n(?:es)? internacional\w*.{0,80}(?:autom[aá]tic|sin intervenci[oó]n)", r"(?:autom[aá]tic|sin intervenci[oó]n).{0,80}devoluci[oó]n(?:es)? internacional\w*")},
    {"id": "RETURNS-02", "text": "TrackFlow no reacondiciona ni revende productos por cuenta propia.", "patterns": (r"trackflow.{0,80}(?:reacondiciona|revende)", r"(?:reacondicionaremos|revenderemos).{0,80}(?:productos|inventario)")},
    {"id": "CARRIER-01", "text": "La selección de carrier la determina el sistema; una excepción requiere aprobación de Carlos Vega.", "patterns": (r"(?:account manager|gerente de cuenta).{0,80}(?:elige|selecciona).{0,60}(?:carrier|transportista)", r"(?:carrier|transportista).{0,60}(?:elecci[oó]n|selecci[oó]n) libre")},
)


@dataclass(frozen=True)
class ReadabilityResult:
    pass_: bool
    score: float
    details: str

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.pass_, "score": self.score, "details": self.details}


@dataclass(frozen=True)
class RelevanceResult:
    pass_: bool
    missing_aspects: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.pass_, "missing_aspects": self.missing_aspects}


@dataclass(frozen=True)
class ComplianceResult:
    pass_: bool
    rule_ids: list[str]
    violations: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {"pass": self.pass_, "rule_ids": self.rule_ids, "violations": self.violations}


def _normalise_aspects(aspects: dict[str, Any]) -> list[str]:
    result: list[str] = []
    summary = aspects.get("resumen_requisitos")
    if isinstance(summary, str) and summary.strip():
        result.append(summary.strip())
    for key in ("entregables", "restricciones_exclusiones", "preguntas_abiertas", "missing_data"):
        values = aspects.get(key, [])
        if isinstance(values, list):
            result.extend(str(item).strip() for item in values if str(item).strip())
    return result


def evaluate_readability(text: str) -> ReadabilityResult:
    words = re.findall(r"\b[\wáéíóúüñÁÉÍÓÚÜÑ]+\b", text)
    sentences = [s for s in re.split(r"[.!?]+", text) if s.strip()]
    if not words:
        return ReadabilityResult(False, 0.0, "La sección está vacía.")
    avg_words = len(words) / max(len(sentences), 1)
    # Transparent, deterministic editorial heuristic, normalized to 0-100.
    score = round(max(0.0, min(100.0, 100 - max(0, avg_words - 20) * 2.5)), 1)
    passed = avg_words <= 28 and len(words) >= 20
    detail = f"{len(words)} palabras; {avg_words:.1f} palabras por oración (máximo recomendado: 28)."
    return ReadabilityResult(passed, score, detail)


def evaluate_relevance(text: str, aspects: dict[str, Any]) -> RelevanceResult:
    body = text.casefold()
    missing = [aspect for aspect in _normalise_aspects(aspects) if not any(
        token.casefold() in body for token in re.findall(r"[\wáéíóúüñÁÉÍÓÚÜÑ]{5,}", aspect)
    )]
    # Long descriptive aspect phrases can share a single relevant keyword; only
    # flag missing entries when no meaningful term is represented at all.
    return RelevanceResult(not missing, missing)


def evaluate_compliance(text: str) -> ComplianceResult:
    violations: list[str] = []
    rule_ids: list[str] = []
    for rule in COMPLIANCE_RULES:
        for pattern in rule["patterns"]:
            match = re.search(pattern, text, re.IGNORECASE | re.DOTALL)
            if match:
                rule_ids.append(rule["id"])
                violations.append(f"{rule['id']}: {rule['text']} Afirmación detectada: {match.group(0)}")
                break
    return ComplianceResult(not violations, rule_ids, violations)


def evaluate_section(section_id: str, text: str, aspects: dict[str, Any]) -> dict[str, Any]:
    # Evaluators return isolated values; only this joiner assembles shared state.
    with ThreadPoolExecutor(max_workers=3) as executor:
        readability_future = executor.submit(evaluate_readability, text)
        relevance_future = executor.submit(evaluate_relevance, text, aspects)
        compliance_future = executor.submit(evaluate_compliance, text)
        readability = readability_future.result()
        relevance = relevance_future.result()
        compliance = compliance_future.result()
    overall = readability.pass_ and relevance.pass_ and compliance.pass_
    feedback: list[str] = []
    if not readability.pass_:
        feedback.append(f"Mejora la legibilidad: {readability.details}")
    if not relevance.pass_:
        feedback.extend(f"Responde explícitamente este aspecto del handoff: {item}" for item in relevance.missing_aspects)
    feedback.extend(compliance.violations)
    return {
        "section_id": section_id,
        "department_id": section_id,
        "readability": readability.to_dict(),
        "relevance": relevance.to_dict(),
        "compliance": compliance.to_dict(),
        "overall_pass": overall,
        "feedback_for_generator": "\n".join(feedback) if feedback else "Evaluación aprobada.",
    }


class DepartmentProposalGenerator:
    """Generator agent dedicated to one department's proposal section."""

    def __init__(self, department: str, instructions: str):
        self.department = department
        self.instructions = instructions

    def generate(self, workstream: dict[str, Any], synthesis_summary: str = "", feedback: str = "") -> str:
        if workstream.get("department") != self.department:
            raise ValueError(f"Generador {self.department} no puede procesar otro departamento")
        aspects = workstream.get("key_aspects") or {}
        response = chat_json(
            system=("Eres redactor de propuestas económicas de TrackFlow. Redacta SOLO la sección solicitada en español profesional. "
                    "No inventes precios, cifras, cobertura ni compromisos; si falta información, declárala como pendiente o supuesto. "
                    f"Alcance exclusivo del agente para {self.department}: {self.instructions} "
                    "Estructura obligatoria: Alcance, Entregables, Consideraciones económicas, Supuestos y datos pendientes."),
            user=(f"Departamento: {self.department}\nResumen synthesizer: {synthesis_summary}\nAspectos del handoff: {aspects}\n"
                  f"Feedback de evaluación anterior (si existe): {feedback}\nDevuelve JSON con campo section_text."),
            temperature=0.2,
        )
        text = response.get("section_text")
        if not isinstance(text, str) or not text.strip():
            raise ValueError(f"El generador {self.department} devolvió una sección vacía")
        return text.strip()


# A distinct configured agent instance and prompt for every Part 1 department.
DEPARTMENT_GENERATORS: dict[str, DepartmentProposalGenerator] = {
    key: DepartmentProposalGenerator(key, instruction)
    for key, instruction in DEPARTMENT_INSTRUCTIONS.items()
}


def generate_department_section(department: str, workstream: dict[str, Any], summary: str = "", feedback: str = "") -> str:
    try:
        generator = DEPARTMENT_GENERATORS[department]
    except KeyError as exc:
        raise ValueError(f"Departamento no soportado: {department}") from exc
    return generator.generate(workstream, summary, feedback)


_HITO9_TO_LEGACY = {
    "warehouse": "operaciones_almacen",
    "lastmile": "ultima_milla_transportistas",
    "reverse": "logistica_inversa",
}


def generate_hito9_section(department: str, workstream: dict[str, Any], summary: str = "", feedback: str = "") -> str:
    """Generate one canonical Hito 9 department using the compatible legacy agents."""
    legacy_id = _HITO9_TO_LEGACY.get(department)
    if legacy_id is None:
        raise ValueError(f"Departamento Hito 9 no soportado: {department}")
    return generate_department_section(legacy_id, {**workstream, "department": legacy_id}, summary, feedback)


def evaluate_hito9_section(department: str, draft: str, aspects: dict[str, Any]) -> dict[str, Any]:
    legacy_id = _HITO9_TO_LEGACY.get(department)
    if legacy_id is None:
        raise ValueError(f"Departamento Hito 9 no soportado: {department}")
    result = evaluate_section(legacy_id, draft, aspects)
    result["department_id"] = department
    return result


async def run_section_cycle(
    workstream: dict[str, Any],
    summary: str,
    *,
    max_iterations: int = MAX_ITERATIONS,
    generator: Callable[..., str] | None = None,
    on_update: Callable[[dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    department = str(workstream.get("department", ""))
    aspects = workstream.get("key_aspects") or {}
    create = generator or generate_department_section
    feedback = ""
    last: dict[str, Any] | None = None
    for iteration in range(1, max(1, max_iterations) + 1):
        if on_update:
            on_update({
                "department": department,
                "draft": last.get("draft") if last else None,
                "evaluation_result": last.get("evaluation_result") if last else None,
                "iteration_count": iteration,
                "status": "generando_borrador",
            })
        draft = await asyncio.to_thread(create, department, workstream, summary, feedback)
        if on_update:
            on_update({
                "department": department,
                "draft": draft,
                "evaluation_result": None,
                "iteration_count": iteration,
                "status": "en_evaluación",
            })
        result = evaluate_section(department, draft, aspects)
        last = {
            "department": department,
            "draft": draft,
            "evaluation_result": result,
            "iteration_count": iteration,
            "status": "completado" if result["overall_pass"] else "en_evaluación",
        }
        if result["overall_pass"]:
            last["status"] = "completado"
            if on_update:
                on_update(last)
            return last
        if on_update:
            on_update({**last, "status": "en_evaluación"})
        feedback = result["feedback_for_generator"]
    assert last is not None
    last["status"] = "needs_human_review"
    if on_update:
        on_update(last)
    return last


async def run_proposal_handoff(
    handoff: dict[str, Any],
    *,
    max_iterations: int = MAX_ITERATIONS,
    generator: Callable[..., str] | None = None,
    on_update: Callable[[str, dict[str, Any]], None] | None = None,
) -> dict[str, Any]:
    """Run department cycles independently; a failed section never cancels peers."""
    ticket_id = handoff.get("ticket_id")
    workstreams = handoff.get("workstreams")
    if not ticket_id or not isinstance(workstreams, list):
        raise ValueError("Handoff inválido: se requiere ticket_id y workstreams")

    async def run_one(workstream: dict[str, Any]) -> dict[str, Any]:
        department = str(workstream.get("department", ""))
        callback = None
        if on_update:
            def callback(update: dict[str, Any]) -> None:
                on_update(department, update)
        try:
            return await run_section_cycle(
                workstream,
                str(handoff.get("synthesizer_summary") or ""),
                max_iterations=max_iterations,
                generator=generator,
                on_update=callback,
            )
        except Exception as exc:
            failure = {
                "department": department,
                "draft": "",
                "evaluation_result": {
                    "section_id": department, "department_id": department,
                    "readability": {"pass": False, "score": 0, "details": f"Error del generador: {exc}"},
                    "relevance": {"pass": False, "missing_aspects": _normalise_aspects(workstream.get("key_aspects") or {})},
                    "compliance": {"pass": False, "rule_ids": [], "violations": []},
                    "overall_pass": False,
                    "feedback_for_generator": f"Error al generar sección: {exc}",
                },
                "iteration_count": 0,
                "status": "needs_human_review",
                "error": str(exc),
            }
            if on_update:
                on_update(department, failure)
            return failure

    results = await asyncio.gather(*(run_one(w) for w in workstreams))
    return {
        **handoff,
        "proposal_sections": results,
        "needs_human_review": any(s["status"] == "needs_human_review" for s in results),
    }
