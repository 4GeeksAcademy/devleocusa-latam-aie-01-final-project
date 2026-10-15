"""Worker agent — extracts key aspects for ONE department.

One worker runs per workstream (in parallel via LangGraph ``Send``). It sees
only its department's extracts + the document metadata — not the full RFP —
which keeps token cost linear and the analysis focused.

Hard rule enforced here and in the prompt: figures/volumes may only be quoted
literally from the extracts. Anything required but absent goes to
``missing_data`` instead of being estimated.
"""

from __future__ import annotations

import json
import time
from typing import Any

from ..config import DEPARTMENT_CATALOG_TEXT, WORKER_MAX_RETRIES, department_contact
from .llm import chat_json

_SYSTEM_PROMPT = f"""Eres un agente worker de TrackFlow especializado en UN departamento.

Recibes: los extractos verbatim de una RFP asignados a tu departamento y los
metadatos del documento. Extrae los "aspectos clave" que el equipo necesita
para responder a la propuesta.

CATALOGO DE DEPARTAMENTOS DE TRACKFLOW (contexto; tu departamento esta marcado):
{DEPARTMENT_CATALOG_TEXT}

REGLAS INQUEBRANTABLES:
- TRADUCE todo lo que el documento pide a tu departamento en aspectos clave
  concretos: requisitos, entregables, restricciones, fechas, cifras.
- Las "cifras_citadas" deben ser LITERALES del documento (copia el texto
  exacto). PROHIBIDO inventar, redondear o estimar cualquier volumen, precio
  o fecha.
- Si el documento no incluye una cifra que tu departamento necesitaria para
  cotizar (ej. volumen mensual de pedidos, nº de SKUs), ponla en
  "missing_data" con una descripcion de que falta. No la deduzcas.
- Si el documento excluye explicitamente algo de tu alcance ("no se requiere
  gestion de transportistas"), reflejalo en "restricciones_exclusiones" para
  que no se cotice de mas.
- "preguntas_abiertas": dudas concretas que Ventas deberia hacerle al cliente.

Responde SIEMPRE con este JSON exacto:
{{
  "resumen_requisitos": "resumen orientado a accion de lo que tu departamento debe atender",
  "entregables": ["que deberiamos preparar/entregar"],
  "cifras_citadas": [{{"valor": "texto literal del documento", "contexto": "donde aparece"}}],
  "restricciones_exclusiones": ["limites o exclusiones explicitas del documento"],
  "preguntas_abiertas": ["duda a resolver con el cliente"],
  "missing_data": ["dato requerido que NO aparece en el documento"],
  "prioridad": "alta|media|baja"
}}"""


def process_workstream(
    workstream: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Run one department worker. Never raises — failures become ``status='error'``."""
    department = str(workstream.get("department", ""))
    contact = department_contact(department)

    user_payload = {
        "departamento": department,
        "intencion_orquestador": workstream.get("intencion", ""),
        "prioridad_orquestador": workstream.get("prioridad", "media"),
        "metadata_documento": metadata or {},
        "extractos": workstream.get("extractos", []),
    }

    parsed: dict[str, Any] | None = None
    last_error: Exception | None = None
    for attempt in range(WORKER_MAX_RETRIES + 1):
        try:
            parsed = chat_json(
                system=_SYSTEM_PROMPT,
                user=json.dumps(user_payload, ensure_ascii=False),
            )
            break
        except Exception as exc:  # network / parse failures — retry then degrade
            last_error = exc
            if attempt < WORKER_MAX_RETRIES:
                time.sleep(min(2**attempt, 8))

    if parsed is None:
        return {
            "department": department,
            "contact_name": contact["contact_name"],
            "contact_role": contact["contact_role"],
            "status": "error",
            "worker_error": f"Worker fallo tras {WORKER_MAX_RETRIES + 1} intentos: {last_error}",
            "key_aspects": None,
        }

    key_aspects = {
        "resumen_requisitos": str(parsed.get("resumen_requisitos") or "").strip()[:2000],
        "entregables": [str(item)[:400] for item in (parsed.get("entregables") or [])][:20],
        "cifras_citadas": [
            {
                "valor": str(fig.get("valor", ""))[:200],
                "contexto": str(fig.get("contexto", ""))[:300],
            }
            for fig in (parsed.get("cifras_citadas") or [])
            if isinstance(fig, dict)
        ][:20],
        "restricciones_exclusiones": [
            str(item)[:400] for item in (parsed.get("restricciones_exclusiones") or [])
        ][:20],
        "preguntas_abiertas": [
            str(item)[:400] for item in (parsed.get("preguntas_abiertas") or [])
        ][:20],
        "missing_data": [str(item)[:400] for item in (parsed.get("missing_data") or [])][:20],
        "prioridad": str(parsed.get("prioridad") or workstream.get("prioridad") or "media"),
    }

    return {
        "department": department,
        "contact_name": contact["contact_name"],
        "contact_role": contact["contact_role"],
        "status": "completado",
        "worker_error": None,
        "key_aspects": key_aspects,
    }
