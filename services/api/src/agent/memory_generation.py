from __future__ import annotations

import json
import os
from typing import Any

from openai import OpenAI

from src.agent.memory_models import MemoryDecisionResult
from src.agent.state import MemoryGeneration


def generate_answer_and_proposal(
    question: str, evidence: list[dict[str, Any]], memories: list[str] | None = None
) -> MemoryGeneration:
    """One generation call returns the user-facing answer and an optional proposal."""
    client = OpenAI(
        api_key=os.getenv("GENERATION_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("GENERATION_BASE_URL", "https://api.openai.com/v1"),
        timeout=30.0,
    )
    context = "\n\n".join(
        str(item.get("text", item))[:4000] for item in evidence
    )
    memory_context = "\n".join(f"- {item}" for item in (memories or [])) or "(ninguna)"
    response = client.chat.completions.create(
        model=os.getenv("GENERATION_MODEL_ID", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        temperature=0.3,
        max_tokens=1200,
        messages=[
            {
                "role": "system",
                "content": (
                    "Eres el agente de soporte interno de TrackFlow. Devuelve JSON con answer y proposal. "
                    "answer es la respuesta en español. proposal debe ser null o un objeto con "
                    "category (carrier_rule/recurring_incident/b2b_report_preference), memory_key, "
                    "content, reason, country (string/null) y repetition_count (integer/null). "
                    "Solo propone: (1) corrección de cobertura/regla de carrier, consolidada por carrier + país "
                    "y zona si aplica; (2) contexto de incidente con patrón repetible demostrado (mínimo dos "
                    "casos; aporta repetition_count), no una falla de TrackFlow inferida; (3) preferencia de "
                    "reporte mensual de cliente B2B recurrente (formato, orden o métricas). Usa una clave estable "
                    "de entidad, nunca ticket/paquete. Memoria es contexto sugerido y no fuente autoritativa: "
                    "una corrección de usuario no cambia políticas compartidas y debe verificarse con RAG/MCP "
                    "antes de darla como hecho. El usuario debe aprobar explícitamente la propuesta. "
                    "Nunca incluyas ni propongas direcciones exactas, ubicaciones sensibles B2B/B2C, rutas "
                    "internas de almacén, identificadores de tracking/paquete, credenciales, contactos, datos "
                    "gubernamentales o información de negociación/contratos comerciales activos. No memorices "
                    "una incidencia aislada, una consulta puntual de tracking, un cierre (p. ej. 'ya quedó resuelto') "
                    "ni una traducción de un solo uso. No propongas por saludos, cálculos, stock puntual o tickets "
                    "aislados. Si falta categoría, recurrencia o ámbito seguro, proposal=null. No escribas memoria."
                ),
            },
            {
                "role": "user",
                "content": json.dumps(
                    {
                        "question": question,
                        "evidence": context,
                        "approved_user_memory": memory_context,
                        "format": {
                            "answer": "string",
                            "proposal": {
                                "category": "carrier_rule|recurring_incident|b2b_report_preference",
                                "memory_key": "stable entity key, not ticket/package",
                                "content": "safe compact summary",
                                "reason": "why useful later",
                                "country": "string|null",
                                "repetition_count": "integer|null",
                            },
                        },
                    },
                    ensure_ascii=False,
                ),
            },
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("El modelo no devolvió respuesta estructurada.")
    return MemoryGeneration.model_validate(json.loads(content))


def classify_pending_decision(proposal: str, message: str) -> dict[str, str | None]:
    """Classify an explicit user decision against exactly one pending proposal."""
    if not message.strip():
        return MemoryDecisionResult(decision="reject").model_dump()
    client = OpenAI(
        api_key=os.getenv("GENERATION_API_KEY") or os.getenv("OPENAI_API_KEY"),
        base_url=os.getenv("GENERATION_BASE_URL", "https://api.openai.com/v1"),
        timeout=15.0,
    )
    response = client.chat.completions.create(
        model=os.getenv("GENERATION_MODEL_ID", "gpt-4o-mini"),
        response_format={"type": "json_object"},
        temperature=0,
        max_tokens=300,
        messages=[
            {
                "role": "system",
                "content": (
                    "Clasifica el mensaje exclusivamente respecto de la propuesta pendiente. Devuelve JSON "
                    "decision con approve/reject/edit/uncertain, explicit_confirmation (boolean), "
                    "edited_content (string/null) y continuation "
                    "con la pregunta nueva si el usuario respondió la propuesta y además hizo otra pregunta. "
                    "Una respuesta ambigua, silencio, cambio de tema o falta de confianza es uncertain. "
                    "Solo un sí/acepto/apruebo inequívoco a guardar exactamente la propuesta activa puede tener "
                    "decision=approve y explicit_confirmation=true. Cualquier otra respuesta debe tener "
                    "explicit_confirmation=false. No infieras aprobación. Una edición no queda aprobada automáticamente."
                ),
            },
            {"role": "user", "content": json.dumps({"proposal": proposal, "message": message}, ensure_ascii=False)},
        ],
    )
    content = response.choices[0].message.content
    if not content:
        raise ValueError("No se pudo clasificar la decisión de memoria.")
    result = MemoryDecisionResult.model_validate(json.loads(content))
    if result.decision.value in {"approve", "uncertain"} and not result.explicit_confirmation:
        result.decision = "reject"
    return result.model_dump()
