#!/usr/bin/env python
"""
Runner script for the TrackFlow pipeline.

Invoked **via subprocess** from the FastAPI reporting module so the API
never imports Prefect directly (avoids dependency conflicts).

Usage (from data/pipelines/):
    uv run python runner.py

Output (single JSON object to stdout):
    {
      "status": "success" | "error",
      "metadata": { ... },
      "kpi_data": { ... } | null,
      "error": "..." | null
    }
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from pipeline import trackflow_pipeline_telemetria


def _extract_metadata(result: dict) -> dict:
    meta = result.get("_metadata", {})
    flow_run_id = result.get("_flow_run_id")
    if not meta:
        return {
            "hora_inicio": None, "hora_fin": None,
            "duracion_segundos": None, "registros_extraidos": None,
            "estado_final": "Completed", "flow_run_id": flow_run_id,
        }
    return {
        "hora_inicio": meta.get("hora_inicio"),
        "hora_fin": meta.get("hora_fin"),
        "duracion_segundos": meta.get("duracion"),
        "registros_extraidos": meta.get("registros_extraidos"),
        "estado_final": meta.get("estado_final", "Completed"),
        "flow_run_id": flow_run_id,
    }


def _extract_kpi(result: dict) -> dict | None:
    kpi_data = result.get("data")
    if isinstance(kpi_data, dict) and "fecha_reporte" in kpi_data:
        return {
            "fecha_reporte": kpi_data.get("fecha_reporte"),
            "id_corrida": kpi_data.get("id_corrida"),
            "timestamp": kpi_data.get("timestamp"),
            "periodo": kpi_data.get("periodo"),
            "volumen_envios": kpi_data.get("volumen_envios"),
            "tasa_entrega_tiempo": kpi_data.get("tasa_entrega_tiempo"),
            "devoluciones": kpi_data.get("devoluciones"),
        }
    return None


def main() -> dict:
    hora_inicio = time.time()
    try:
        result = trackflow_pipeline_telemetria()
    except Exception as exc:
        return {"status": "error", "error": str(exc), "metadata": None, "kpi_data": None}
    hora_fin = time.time()
    metadata = _extract_metadata(result)
    metadata["duracion_segundos"] = round(hora_fin - hora_inicio, 3)
    kpi_data = _extract_kpi(result)
    return {"status": "success", "error": None, "metadata": metadata, "kpi_data": kpi_data}


if __name__ == "__main__":
    print(json.dumps(main()))
