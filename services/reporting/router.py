"""FastAPI router for TrackFlow executive reporting.

Three endpoints:
  1. ``GET  /reporting/status``  — última ejecución del pipeline.
  2. ``POST /reporting/run``     — disparar corrida manual.
  3. ``GET  /reporting/kpis``    — consultar KPIs históricos.

Importa **directamente** la función de orquestación desde
``data/pipelines/pipeline.py`` (sin duplicar lógica de negocio) y persiste
los resultados en TinyDB via ``.store``.

Sigue las mismas convenciones que el resto de routers (JWT auth, Spanish
error messages, prefix + tags).
"""

from __future__ import annotations

import sys
import time
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.models.user import User
from src.services.auth_service import get_current_user

from . import models as reporting_models
from . import store as reporting_store

# ------------------------------------------------------------------------
#  Import directo de data/pipelines/ (sin duplicar lógica de negocio)
# ------------------------------------------------------------------------

_PIPELINES_DIR = (
    Path(__file__).resolve().parent.parent.parent / "data" / "pipelines"
)
if str(_PIPELINES_DIR) not in sys.path:
    sys.path.insert(0, str(_PIPELINES_DIR))

from pipeline import trackflow_pipeline_telemetria  # type: ignore[import-untyped]  # noqa: E402

# ------------------------------------------------------------------------
#  Router
# ------------------------------------------------------------------------

router = APIRouter(
    prefix="/reporting",
    tags=["reporting"],
)

_DESTINO_TABLAS = [
    "executive_kpis (TinyDB — services/reporting/data/reporting.json)",
]


# ------------------------------------------------------------------------
#  Helpers
# ------------------------------------------------------------------------


def _extract_metadata(result: dict[str, Any]) -> dict[str, Any]:
    """Extrae los metadatos de la ejecucion del diccionario devuelto por el pipeline."""
    meta = result.get("_metadata", {})
    flow_run_id = result.get("_flow_run_id")

    # Convertir UUID a string para serializacion JSON
    if flow_run_id is not None:
        flow_run_id = str(flow_run_id)

    if not meta:
        return {
            "hora_inicio": None,
            "hora_fin": None,
            "duracion_segundos": None,
            "registros_extraidos": None,
            "estado_final": "Completed",
            "flow_run_id": flow_run_id,
            "errores": [],
        }

    raw_flow_run = meta.get("flow_run_id", flow_run_id)
    if raw_flow_run is not None:
        raw_flow_run = str(raw_flow_run)

    return {
        "hora_inicio": meta.get("hora_inicio"),
        "hora_fin": meta.get("hora_fin"),
        "duracion_segundos": meta.get("duracion_segundos"),
        "registros_extraidos": meta.get("registros_extraidos"),
        "estado_final": meta.get("estado_final", "Completed"),
        "flow_run_id": raw_flow_run,
        "errores": meta.get("errores", []),
    }


def _extract_kpi(result: dict[str, Any]) -> dict[str, Any] | None:
    """Extrae el registro de KPIs del resultado del pipeline, si existe.

    Busca en ``result["data"]`` (estructura devuelta por ``cargar_resultados``)
    y verifica que contenga los campos esperados del contrato del dashboard.
    """
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


# ------------------------------------------------------------------------
#  1.  GET /reporting/status  —  Ultima ejecucion
# ------------------------------------------------------------------------


@router.get(
    "/status",
    response_model=reporting_models.PipelineStatusResponse,
    summary="Consultar estado de la ultima ejecucion del pipeline",
    description=(
        "Retorna los metadatos de la corrida mas reciente del pipeline "
        "Prefect ``trackflow_pipeline_telemetria``: horarios, duracion, "
        "cantidad de eventos procesados, estado final y errores.\n\n"
        "Si el pipeline nunca se ha ejecutado, ``ultima_ejecucion`` sera "
        "``None`` (no es un error)."
    ),
)
def get_pipeline_status(
    current_user: User = Depends(get_current_user),
) -> reporting_models.PipelineStatusResponse:
    last_exec = reporting_store.get_last_execution()

    if last_exec is None:
        return reporting_models.PipelineStatusResponse(
            pipeline="trackflow_pipeline_telemetria",
            ultima_ejecucion=None,
            tablas_destino=_DESTINO_TABLAS,
        )

    return reporting_models.PipelineStatusResponse(
        pipeline="trackflow_pipeline_telemetria",
        ultima_ejecucion=reporting_models.PipelineExecutionMetadata(
            hora_inicio=last_exec.get("hora_inicio"),
            hora_fin=last_exec.get("hora_fin"),
            duracion_segundos=last_exec.get("duracion_segundos"),
            registros_extraidos=last_exec.get("registros_extraidos"),
            estado_final=last_exec.get("estado_final"),
            flow_run_id=last_exec.get("flow_run_id"),
            errores=last_exec.get("errores", []),
        ),
        tablas_destino=_DESTINO_TABLAS,
    )


# ------------------------------------------------------------------------
#  2.  POST /reporting/run  —  Disparar corrida manual
# ------------------------------------------------------------------------


@router.post(
    "/run",
    response_model=reporting_models.TriggerResponse,
    summary="Disparar una corrida manual del pipeline",
    description=(
        "Ejecuta el pipeline completo de telemetria de forma sincrona: "
        "extrae los eventos de muestra, transforma los KPIs, "
        "persiste los resultados y notifica el estado.\n\n"
        "Importa la funcion directamente de ``data/pipelines/pipeline.py`` "
        "sin duplicar logica de negocio.\n\n"
        "Retorna los metadatos completos de la ejecucion, incluyendo la "
        "lista de errores si los hubo.\n"
        "Si ocurre un error fatal, se retorna un HTTP 502 "
        "con el detalle del fallo en espanol."
    ),
)
def trigger_pipeline(
    current_user: User = Depends(get_current_user),
) -> reporting_models.TriggerResponse:
    try:
        hora_inicio = time.time()
        result = trackflow_pipeline_telemetria()
        hora_fin = time.time()

        metadata = _extract_metadata(result)
        metadata["duracion_segundos"] = round(hora_fin - hora_inicio, 3)

        # Persistir metadata para GET /status
        reporting_store.save_last_execution(metadata)

        # Persistir KPIs si el pipeline los produjo
        kpi_record = _extract_kpi(result)
        if kpi_record:
            reporting_store.save_kpi_record(kpi_record)

        return reporting_models.TriggerResponse(
            status="success",
            detail="Pipeline ejecutado correctamente. "
            "Los KPIs han sido calculados y persistidos.",
            flow_run_id=metadata.get("flow_run_id"),
            metadata=reporting_models.PipelineExecutionMetadata(
                hora_inicio=metadata.get("hora_inicio"),
                hora_fin=metadata.get("hora_fin"),
                duracion_segundos=metadata.get("duracion_segundos"),
                registros_extraidos=metadata.get("registros_extraidos"),
                estado_final=metadata.get("estado_final"),
                flow_run_id=metadata.get("flow_run_id"),
                errores=metadata.get("errores", []),
            ),
        )

    except RuntimeError as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error en la ejecucion del pipeline: {exc}",
        ) from exc
    except Exception as exc:
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Error inesperado al ejecutar el pipeline: {exc}",
        ) from exc


# ------------------------------------------------------------------------
#  3.  GET /reporting/kpis  —  Consultar KPIs
# ------------------------------------------------------------------------


@router.get(
    "/kpis",
    response_model=reporting_models.KPIListResponse,
    summary="Consultar KPIs ejecutivos historicos",
    description=(
        "Retorna el listado de registros de KPIs producidos por el pipeline, "
        "directamente desde la tabla de destino del esquema reporting.\n\n"
        "Se puede filtrar por ``fecha_reporte`` y/o ``id_corrida``. "
        "El parametro ``limit`` controla la cantidad maxima de registros "
        "devueltos (por defecto 100, ordenados del mas reciente al mas antiguo).\n\n"
        "Si no hay registros, se retorna una lista vacia (no es un error)."
    ),
)
def get_kpis(
    fecha_reporte: str | None = Query(
        None,
        description="Filtrar por fecha de reporte (formato YYYY-MM-DD).",
    ),
    id_corrida: str | None = Query(
        None,
        description="Filtrar por identificador unico de corrida.",
    ),
    limit: int = Query(
        100,
        ge=1,
        le=1000,
        description="Cantidad maxima de registros a retornar (entre 1 y 1000).",
    ),
    current_user: User = Depends(get_current_user),
) -> reporting_models.KPIListResponse:
    records = reporting_store.get_all_kpi_records(
        fecha_reporte=fecha_reporte,
        id_corrida=id_corrida,
        limit=limit,
    )

    return reporting_models.KPIListResponse(
        registros=[reporting_models.ExecutiveKPIs(**rec) for rec in records],
        total=len(records),
    )
