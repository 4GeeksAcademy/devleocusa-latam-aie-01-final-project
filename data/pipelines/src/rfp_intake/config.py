"""Shared configuration for the rfp_intake pipeline.

Loads the repo-root ``.env`` (same pattern as ``pipelines/rag.py``) and
defines the TrackFlow department catalog straight from CONTEXT-company.md.
The catalog is the single source of truth for the orchestrator, the workers
and the synthesizer — department names, owners and scope NEVER drift.
"""

from __future__ import annotations

import os
from pathlib import Path
from typing import Any

from dotenv import load_dotenv

# Repo root: data/pipelines/src/rfp_intake/config.py -> parents[4]
_ENV_PATH = Path(__file__).resolve().parents[4] / ".env"
load_dotenv(_ENV_PATH)

# ── LLM (reuses the existing GENERATION_* credentials from the RAG stack) ──

LLM_MODEL: str = os.getenv("RFP_AGENT_MODEL") or os.getenv("GENERATION_MODEL_ID", "gpt-4o-mini")
LLM_API_KEY: str = os.getenv("RFP_AGENT_API_KEY") or os.getenv("GENERATION_API_KEY", "")
LLM_BASE_URL: str | None = os.getenv("RFP_AGENT_BASE_URL") or os.getenv("GENERATION_BASE_URL") or None

#: Below this confidence the classifier's rejection demands human review.
LOW_CONFIDENCE_THRESHOLD: float = float(os.getenv("RFP_LOW_CONFIDENCE_THRESHOLD", "0.6"))

#: Artifacts root for uploaded PDFs and their converted Markdown.
RAW_DATA_DIR: Path = Path(os.getenv("RFP_RAW_DATA_DIR", str(Path(__file__).resolve().parents[4] / "data" / "raw")))

#: Workers retry at most this many times before their section is marked `error`.
WORKER_MAX_RETRIES: int = int(os.getenv("RFP_WORKER_MAX_RETRIES", "2"))

# ── TrackFlow department catalog (CONTEXT-company.md) ───────────────────
# Key must match DepartmentKey in services/api/src/models/rfp.py.

DEPARTMENT_CATALOG: list[dict[str, Any]] = [
    {
        "key": "operaciones_almacen",
        "name": "Operaciones de Almacén",
        "owner": "Ana Whitfield",
        "role": "Directora de Operaciones de Almacén",
        "scope": (
            "Recepcion, picking, packing y preparacion de pedidos; gestion de "
            "inventario en los almacenes de Los Angeles y Zaragoza; integracion "
            "de pedidos entrantes; alertas de stock."
        ),
    },
    {
        "key": "ultima_milla_transportistas",
        "name": "Última Milla y Gestión de Transportistas",
        "owner": "Carlos Vega",
        "role": "Head de Última Milla y Transportistas",
        "scope": (
            "Seleccion y asignacion de transportista (UPS, FedEx, DHL, MRW, SEUR "
            "y locales), tracking unificado, gestion de entregas fallidas e "
            "incidencias de ruta, portales de seguimiento."
        ),
    },
    {
        "key": "logistica_inversa",
        "name": "Logística Inversa",
        "owner": "Sofía Ramos",
        "role": "Lead de Logística Inversa",
        "scope": (
            "Devoluciones: aprobacion/rechazo, recogida, inspeccion de producto, "
            "reacondicionamiento, restock y analisis de patrones de devolucion."
        ),
    },
    {
        "key": "experiencia_cliente",
        "name": "Experiencia del Cliente (CX)",
        "owner": "Valentina Cruz",
        "role": "CX Manager",
        "scope": (
            "Atencion al cliente B2B (marcas) y B2C (consumidores): tickets, "
            "consultas de seguimiento y devoluciones, base de conocimiento, "
            "multiidioma (ES/EN)."
        ),
    },
    {
        "key": "comercial_cuentas",
        "name": "Comercial y Relación con Clientes",
        "owner": "Miguel Torres",
        "role": "Head Comercial y Relación con Clientes",
        "scope": (
            "Cuentas de marcas, contratos anuales y renovaciones, propuestas "
            "economicas y estructura de precios, informes mensuales a cliente, "
            "salud de cuenta y CRM."
        ),
    },
    {
        "key": "tecnologia",
        "name": "Tecnología",
        "owner": "Andrés Kim",
        "role": "CTO",
        "scope": (
            "Integraciones y APIs (ERP, WMS, e-commerce), telemetría y logging, "
            "pipeline de datos, seguridad, y viabilidad tecnica de lo pedido."
        ),
    },
    {
        "key": "direccion_ejecutiva",
        "name": "Dirección Ejecutiva",
        "owner": "CEO",
        "role": "Dirección Ejecutiva",
        "scope": (
            "Decisiones strategicas, margen y encaje de la cuenta, riesgo de "
            "operacion transfronteriza (US/Espana), KPIs globales del negocio."
        ),
    },
]

DEPARTMENT_KEYS: list[str] = [d["key"] for d in DEPARTMENT_CATALOG]

#: Compact catalog string injected into agent prompts.
DEPARTMENT_CATALOG_TEXT: str = "\n".join(
    f"- {d['key']} | {d['name']} | responsable: {d['owner']} ({d['role']}) | alcance: {d['scope']}"
    for d in DEPARTMENT_CATALOG
)


def department_contact(department_key: str) -> dict[str, str]:
    """Return owner/role for a known department (or the CEO as escalation)."""
    for dept in DEPARTMENT_CATALOG:
        if dept["key"] == department_key:
            return {"contact_name": str(dept["owner"]), "contact_role": str(dept["role"])}
    return {"contact_name": "CEO", "contact_role": "Dirección Ejecutiva"}


def make_llm() -> Any:
    """Build the shared OpenAI-compatible client for all rfp_intake agents."""
    from openai import OpenAI

    kwargs: dict[str, Any] = {"api_key": LLM_API_KEY or "missing-key"}
    if LLM_BASE_URL:
        kwargs["base_url"] = LLM_BASE_URL
    return OpenAI(**kwargs)
