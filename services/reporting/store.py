"""Simple TinyDB-backed store for pipeline execution metadata and KPI records.

This module provides persistence for:
  - The latest pipeline execution metadata (used by ``GET /reporting/status``).
  - KPI records produced by the pipeline (used by ``GET /reporting/kpis``).

It follows the same TinyDB pattern used in ``services/api/src/database.py``.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from tinydb import TinyDB, Query

# ── Data directory ───────────────────────────────────────────────────────

DATA_DIR = Path(__file__).resolve().parent / "data"
DATA_DIR.mkdir(parents=True, exist_ok=True)
DB_PATH = str(DATA_DIR / "reporting.json")


# ── Database handle ──────────────────────────────────────────────────────

_db = TinyDB(DB_PATH)
_pipeline_table = _db.table("pipeline_executions")
_kpis_table = _db.table("executive_kpis")


# ── Pipeline execution store ─────────────────────────────────────────────


def save_last_execution(metadata: dict[str, Any]) -> None:
    """Persist the metadata of the latest pipeline execution.

    We keep only **one** record (the most recent run).
    """
    _pipeline_table.truncate()
    _pipeline_table.insert(metadata)


def get_last_execution() -> dict[str, Any] | None:
    """Return the metadata of the most recent pipeline execution, or ``None``."""
    records = _pipeline_table.all()
    if not records:
        return None
    return records[-1]


# ── KPI records store ────────────────────────────────────────────────────


def save_kpi_record(kpi_data: dict[str, Any]) -> None:
    """Persist a KPI record, performing an **upsert** by (fecha_reporte, id_corrida).

    This mirrors the upsert strategy simulated in the pipeline's
    ``cargar_resultados()`` task.
    """
    KPIQuery = Query()
    fecha_reporte = kpi_data.get("fecha_reporte", "unknown")
    id_corrida = kpi_data.get("id_corrida", "unknown")

    existing = _kpis_table.search(
        (KPIQuery.fecha_reporte == fecha_reporte)
        & (KPIQuery.id_corrida == id_corrida)
    )

    if existing:
        _kpis_table.update(kpi_data, doc_ids=[existing[0].doc_id])
    else:
        _kpis_table.insert(kpi_data)


def get_all_kpi_records(
    fecha_reporte: str | None = None,
    id_corrida: str | None = None,
    limit: int = 100,
) -> list[dict[str, Any]]:
    """Return KPI records with optional filtering by ``fecha_reporte`` or ``id_corrida``."""
    KPIQuery = Query()

    conditions = []
    if fecha_reporte:
        conditions.append(KPIQuery.fecha_reporte == fecha_reporte)
    if id_corrida:
        conditions.append(KPIQuery.id_corrida == id_corrida)

    if conditions:
        query = conditions[0]
        for cond in conditions[1:]:
            query = query & cond
        results = _kpis_table.search(query)
    else:
        results = _kpis_table.all()

    # Return most recent first, limited to `limit`
    return list(reversed(results))[:limit]