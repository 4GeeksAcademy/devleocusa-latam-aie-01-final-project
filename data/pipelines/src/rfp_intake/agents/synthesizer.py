"""Synthesizer agent — consolidates every department section for Ventas.

Produces the acceptance-criteria artifact: a summary that lets Ventas know,
WITHOUT opening the original PDF, what each department must do and who owns
it. Contradictions between workers are surfaced, never silently merged (D4).
"""

from __future__ import annotations

import json
from typing import Any

from ..config import DEPARTMENT_CATALOG_TEXT
from .llm import chat_json

_SYSTEM_PROMPT = f"""Eres el synthesizer del flujo de recepcion de RFPs de TrackFlow.

Recibes los "key_aspects" consolidados de los workers por departamento y los
metadatos del documento. Tu salida la lee el equipo de Ventas sin haber visto
el PDF original.

CATALOGO DE DEPARTAMENTOS DE TRACKFLOW:
{DEPARTMENT_CATALOG_TEXT}

REGLAS:
- El "resumen" debe responder, en texto plano y sin jerga: (1) que pide el
  cliente y a que plazo, (2) que le toca a CADA departamento, (3) a QUE
  RESPONSABLE interno pedir cada cosa (usa los nombres del catalogo).
- Cita las cifras tal como las dieron los workers (los workers ya garantizan
  que son literales del documento). No las recalcules ni las interpretes.
- Si dos departamentos reportan cifras o hechos contradictorios sobre lo
  mismo, NO los fusiones: anotalo en "contradicciones" con que departamento
  dijo que, para que Ventas lo resuelva.
- Si hay "missing_data" relevante, reflejalo en el resumen como datos que hay
  que pedirle al cliente antes de poder cotizar.
- "handoff": lista plana para la Parte 2 (generacion de la propuesta), con un
  item por departamento incluyendo su "key_aspects" tal cual.

Responde SIEMPRE con este JSON exacto:
{{
  "resumen": "texto para Ventas",
  "contradicciones": [{{"tema": "...", "version_a": "...", "version_b": "..."}}],
  "handoff": [
    {{
      "department": "clave_del_catalogo",
      "contact_name": "responsable interno",
      "contact_role": "rol",
      "key_aspects": {{}}
    }}
  ]
}}"""


def _fallback_synthesis(sections: list[dict[str, Any]]) -> dict[str, Any]:
    """Deterministic summary when the LLM output is unusable."""
    lines: list[str] = []
    handoff: list[dict[str, Any]] = []
    for section in sections:
        department = str(section.get("department", ""))
        contact_name = str(section.get("contact_name", ""))
        status = str(section.get("status", ""))
        aspects = section.get("key_aspects") or {}
        resumen = str(aspects.get("resumen_requisitos", "")) if isinstance(aspects, dict) else ""
        if status == "error":
            lines.append(f"- {department}: worker con error, requiere reejecucion manual.")
        else:
            lines.append(f"- {department} (pedir a {contact_name}): {resumen or 'sin resumen'}")
        handoff.append(
            {
                "department": department,
                "contact_name": contact_name,
                "contact_role": str(section.get("contact_role", "")),
                "key_aspects": aspects,
            }
        )
    return {
        "resumen": "Resumen consolidado (modo fallback):\n" + "\n".join(lines),
        "contradicciones": [],
        "handoff": handoff,
    }


def synthesize_sections(
    sections: list[dict[str, Any]],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Merge department sections into the Ventas-facing summary + Parte 2 handoff."""
    user_payload = {
        "metadata": metadata or {},
        "secciones": [
            {
                "department": s.get("department"),
                "contact_name": s.get("contact_name"),
                "status": s.get("status"),
                "key_aspects": s.get("key_aspects"),
                "worker_error": s.get("worker_error"),
            }
            for s in sections
        ],
    }
    try:
        parsed = chat_json(
            system=_SYSTEM_PROMPT,
            user=json.dumps(user_payload, ensure_ascii=False),
        )
    except Exception:
        return _fallback_synthesis(sections)

    resumen = str(parsed.get("resumen") or "").strip()
    handoff = parsed.get("handoff")
    if not resumen or not isinstance(handoff, list) or not handoff:
        return _fallback_synthesis(sections)

    contradictions = [
        {
            "tema": str(item.get("tema", ""))[:300],
            "version_a": str(item.get("version_a", ""))[:300],
            "version_b": str(item.get("version_b", ""))[:300],
        }
        for item in (parsed.get("contradicciones") or [])
        if isinstance(item, dict)
    ][:10]

    normalized_handoff: list[dict[str, Any]] = []
    for item in handoff:
        if not isinstance(item, dict):
            continue
        normalized_handoff.append(
            {
                "department": str(item.get("department", "")),
                "contact_name": str(item.get("contact_name", "")),
                "contact_role": str(item.get("contact_role", "")),
                "key_aspects": item.get("key_aspects") if isinstance(item.get("key_aspects"), dict) else {},
            }
        )

    return {
        "resumen": resumen,
        "contradicciones": contradictions,
        "handoff": normalized_handoff,
    }
