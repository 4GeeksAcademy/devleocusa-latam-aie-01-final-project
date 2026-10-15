"""Classifier agent — gatekeeper of the rfp_intake graph.

Reads the converted Markdown and decides whether the document is a genuine
request for proposal addressed to TrackFlow. A rejection is NEVER silent: it
always carries a human-readable reason that ends up in the ticket.

Calibrated against the CONTEXT sample PDFs:

    modaviva/CONTEXT-trackflow-request-1.pdf   formal RFP        → accept
    lunacosmetics/CONTEXT-trackflow-request-2.pdf informal email → accept
    rapidship/CONTEXT-trackflow-request-3.pdf  vendor pitch      → reject
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Any

from ..config import DEPARTMENT_CATALOG_TEXT, DEPARTMENT_KEYS
from .llm import chat_json

_SYSTEM_PROMPT = f"""Eres el agente clasificador de RFPs de TrackFlow.

TrackFlow es un 3PL (logistica externa) de ultima milla y almacenaje con
almacenes en Los Angeles (EEUU) y Zaragoza (Espana). Recibe documentos de
prospectos/clientes (marcas e-commerce) que piden una propuesta economica de
servicios logisticos: almacenaje, picking/pack, envio/ultima milla, gestion de
devoluciones, integraciones e informes.

TU TAREA: decidir si el documento recibido es una RFP (Request for Proposal)
dirigida A TrackFlow, es decir, una solicitud de propuesta que debemos atender.

ACEPTA como RFP (is_rfp = true):
- Documentos formales con encabezado "RFP"/"Request for Proposal", alcance de
  servicios, criterios de evaluacion, fechas de entrega de propuesta.
- Correos informales que piden expresamente una propuesta o presupuesto de
  servicios logisticos ("could you send a proposal", "envianos una propuesta").

RECHAZA (is_rfp = false):
- Ofertas comerciales dirigidas A TrackFlow (alguien nos vende sus servicios,
  p. ej. un transportista ofreciendo tarifas). No somos nosotros los que
  debemos proponer: nos estan proponiendo a nosotros.
- Facturas, recibos, nominas, documentacion legal interna, newsletters,
  confirmaciones de pedido u otros documentos que no solicitan propuesta.
- Documentos sin ninguna relacion con servicios logisticos.

DEPARTAMENTOS de TrackFlow (catalogo cerrado; no inventes otros):
{DEPARTMENT_CATALOG_TEXT}

Para cada RFP valida, lista los departamentos cuyo alcance aparece mencionado
o implicado en el documento, usando SOLO las claves del catalogo. Si el
documento menciona un area que no existe en el catalogo, no la inventes: ponla
en "unmapped_mentions".

Responde SIEMPRE con este JSON exacto:
{{
  "is_rfp": true|false,
  "confidence": 0.0-1.0,
  "reason": "explicacion breve y concreta para el equipo de Ventas",
  "detected_departments": ["clave1", "clave2"],
  "unmapped_mentions": ["area_inexistente"]
}}"""


@dataclass(frozen=True)
class ClassifierDecision:
    """Typed outcome of the classification step."""

    is_rfp: bool
    confidence: float
    reason: str
    detected_departments: list[str] = field(default_factory=list)
    unmapped_mentions: list[str] = field(default_factory=list)


def _normalize_departments(raw: Any) -> tuple[list[str], list[str]]:
    """Split model output into (known catalog keys, unmapped mentions)."""
    known: list[str] = []
    unmapped: list[str] = []
    if not isinstance(raw, list):
        return known, unmapped
    for item in raw:
        key = str(item).strip().lower().replace(" ", "_").replace("-", "_")
        if key in DEPARTMENT_KEYS:
            if key not in known:
                known.append(key)
        elif key and key not in unmapped:
            unmapped.append(str(item).strip())
    return known, unmapped


def _coerce_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.strip().lower() in {"true", "si", "sí", "yes", "rfp"}
    return bool(value)


def _coerce_confidence(value: Any) -> float:
    try:
        confidence = float(value)
    except (TypeError, ValueError):
        return 0.5
    return max(0.0, min(1.0, confidence))


def classify_document(markdown: str, metadata: dict[str, Any] | None = None) -> ClassifierDecision:
    """Classify the converted Markdown as a TrackFlow RFP or not.

    Pure with respect to the database: takes text, returns a decision.
    """
    user_payload = {
        "metadata_extraida": metadata or {},
        "documento_markdown": markdown[:24000],
    }
    parsed = chat_json(
        system=_SYSTEM_PROMPT,
        user=json.dumps(user_payload, ensure_ascii=False),
    )

    detected, unmapped = _normalize_departments(parsed.get("detected_departments"))
    unmapped_from_model = [
        str(item).strip() for item in (parsed.get("unmapped_mentions") or []) if str(item).strip()
    ]
    for mention in unmapped_from_model:
        if mention not in unmapped:
            unmapped.append(mention)

    reason = str(parsed.get("reason") or "Sin razon proporcionada.").strip()

    return ClassifierDecision(
        is_rfp=_coerce_bool(parsed.get("is_rfp")),
        confidence=_coerce_confidence(parsed.get("confidence")),
        reason=reason,
        detected_departments=detected,
        unmapped_mentions=unmapped,
    )
