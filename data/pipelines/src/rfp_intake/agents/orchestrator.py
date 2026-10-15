"""Orchestrator agent — decomposes a valid RFP into per-department workstreams.

The orchestrator decides *which* TrackFlow departments must look at the RFP
and captures the relevant extracts for each one, so workers never ingest the
full document (token cost control) and never speculate about volumes that are
not literally in the RFP.
"""

from __future__ import annotations

import json
from typing import Any

from ..config import DEPARTMENT_CATALOG_TEXT, DEPARTMENT_KEYS, department_contact
from .llm import chat_json

_MAX_EXCERPT_CHARS = 1600

_SYSTEM_PROMPT = f"""Eres el orquestador de recepcion de RFPs de TrackFlow.

Recibes una RFP YA validada, sus metadatos y los departamentos detectados por
el clasificador. Tu trabajo es descomponer el documento en workstreams, uno
por departamento de TrackFlow cuyo alcance toque la RFP, extrayendo los
fragmentos relevantes del documento para cada uno.

CATALOGO DE DEPARTAMENTOS (claves, responsables y alcance):
{DEPARTMENT_CATALOG_TEXT}

REGLAS:
- Usa SOLO claves del catalogo en "department". Nunca inventes departamentos.
- Para cada departamento asigna "prioridad": "alta" si la RFP le pide
  explicitamente algo, "media" si es requisito implicito, "baja" si solo es
  contexto.
- En "extractos" copia textualmente (verbatim) los fragmentos del documento
  relevantes para ese departamento, incluidas cifras, fechas y exclusiones
  ("no se requiere X"). NO resumas ni reescribas cifras: el worker las debe ver
  tal cual aparecen.
- Un departamento puede quedar con extractos vacios si la RFP no habla de el;
  en ese caso "intencion" explica por que se incluye.
- Si el clasificador detecto areas fuera del catalogo ("unmapped"), IGNORALAS:
  no existen en TrackFlow.

Responde SIEMPRE con este JSON exacto:
{{
  "workstreams": [
    {{
      "department": "clave_del_catalogo",
      "prioridad": "alta|media|baja",
      "intencion": "que debe averiguar/preparar este departamento",
      "extractos": ["fragmento verbatim del documento"]
    }}
  ]
}}"""


def _fallback_workstreams(detected: list[str]) -> list[dict[str, Any]]:
    """Deterministic workstreams when the LLM output is unusable."""
    workstreams: list[dict[str, Any]] = []
    for key in detected:
        if key not in DEPARTMENT_KEYS:
            continue
        contact = department_contact(key)
        workstreams.append(
            {
                "department": key,
                "prioridad": "media",
                "intencion": "Revision manual: el orquestador no devolvio un plan valido.",
                "extractos": [],
                "contact_name": contact["contact_name"],
                "contact_role": contact["contact_role"],
            }
        )
    return workstreams


def plan_workstreams(
    markdown: str,
    metadata: dict[str, Any],
    detected_departments: list[str],
) -> list[dict[str, Any]]:
    """Produce one work item per department with verbatim extracts.

    Each workstream: {department, prioridad, intencion, extractos[], contact_*}.
    """
    user_payload = {
        "metadata": metadata,
        "departamentos_detectados": detected_departments,
        "documento_markdown": markdown[:24000],
    }
    try:
        parsed = chat_json(
            system=_SYSTEM_PROMPT,
            user=json.dumps(user_payload, ensure_ascii=False),
        )
    except Exception:
        return _fallback_workstreams(detected_departments)

    raw_workstreams = parsed.get("workstreams")
    if not isinstance(raw_workstreams, list) or not raw_workstreams:
        return _fallback_workstreams(detected_departments)

    workstreams: list[dict[str, Any]] = []
    seen: set[str] = set()
    for item in raw_workstreams:
        if not isinstance(item, dict):
            continue
        department = str(item.get("department", "")).strip()
        if department not in DEPARTMENT_KEYS or department in seen:
            continue
        seen.add(department)

        extractos = [
            str(excerpt)[:_MAX_EXCERPT_CHARS]
            for excerpt in (item.get("extractos") or [])
            if isinstance(excerpt, str) and excerpt.strip()
        ]
        prioridad = str(item.get("prioridad", "media")).strip().lower()
        if prioridad not in {"alta", "media", "baja"}:
            prioridad = "media"

        contact = department_contact(department)
        workstreams.append(
            {
                "department": department,
                "prioridad": prioridad,
                "intencion": str(item.get("intencion", "")).strip()[:600],
                "extractos": extractos,
                "contact_name": contact["contact_name"],
                "contact_role": contact["contact_role"],
            }
        )

    return workstreams or _fallback_workstreams(detected_departments)
