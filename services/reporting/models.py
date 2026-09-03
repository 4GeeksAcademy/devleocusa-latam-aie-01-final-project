"""Pydantic schemas for the reporting API — pipeline metadata & executive KPIs.

All models are pure Pydantic v2, following the same conventions as
``services/api/src/models/schemas.py`` (field descriptions, snake_case,
strict type annotations).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


# ─────────────────────────────────────────────────────────────────────────
# Pipeline execution metadata
# ─────────────────────────────────────────────────────────────────────────


class PipelineExecutionMetadata(BaseModel):
    """Metadata of a single Prefect flow run."""

    hora_inicio: str | None = Field(
        None, description="Timestamp de inicio de la ejecucion (ISO 8601)."
    )
    hora_fin: str | None = Field(
        None, description="Timestamp de finalizacion de la ejecucion (ISO 8601)."
    )
    duracion_segundos: float | None = Field(
        None, ge=0, description="Duracion total de la ejecucion en segundos."
    )
    registros_extraidos: int | None = Field(
        None, ge=0, description="Cantidad de eventos extraidos en la corrida."
    )
    estado_final: str | None = Field(
        None, description="Estado final de la ejecucion (e.g. 'Completed')."
    )
    flow_run_id: str | None = Field(
        None, description="Identificador unico del flow run en Prefect."
    )
    errores: list[str] = Field(
        default_factory=list,
        description="Lista de errores capturados durante la ejecucion (vacio si todo fue exitoso).",
    )


class PipelineStatusResponse(BaseModel):
    """Respuesta del endpoint de estado de la ultima ejecucion."""

    pipeline: str = Field(
        "trackflow_pipeline_telemetria",
        description="Nombre del flujo de Prefect.",
    )
    ultima_ejecucion: PipelineExecutionMetadata | None = Field(
        None,
        description="Metadata de la ejecucion mas reciente. "
        "``None`` si aun no se ha ejecutado ninguna corrida.",
    )
    tablas_destino: list[str] = Field(
        ..., description="Tablas donde se persisten los KPIs."
    )


# ─────────────────────────────────────────────────────────────────────────
# Manual trigger
# ─────────────────────────────────────────────────────────────────────────


class TriggerResponse(BaseModel):
    """Respuesta tras disparar una corrida manual del pipeline."""

    status: str = Field(..., description="Estado de la ejecucion disparada.")
    detail: str = Field(..., description="Mensaje descriptivo del resultado.")
    flow_run_id: str | None = Field(
        None,
        description="Identificador del flow run generado (si se completo).",
    )
    metadata: PipelineExecutionMetadata | None = Field(
        None,
        description="Metadata completa de la ejecucion.",
    )


# ─────────────────────────────────────────────────────────────────────────
# Executive KPIs (reporting schema)
# ─────────────────────────────────────────────────────────────────────────


class VolumenEnvios(BaseModel):
    """KPI: volumen de envios, total y por almacen."""

    total: int = Field(..., ge=0, description="Volumen total de envios.")
    por_almacen: dict[str, int] = Field(
        ..., description="Desglose por almacen (ej. {'los-angeles': 10, 'zaragoza': 5})."
    )


class TasaEntregaTiempo(BaseModel):
    """KPI: tasa de entrega a tiempo (on-time delivery)."""

    porcentaje: float = Field(
        ..., ge=0.0, le=100.0, description="Porcentaje de entregas a tiempo."
    )
    entregas_on_time: int = Field(
        ..., ge=0, description="Cantidad de entregas realizadas a tiempo."
    )
    entregas_totales: int = Field(
        ..., ge=0, description="Cantidad total de entregas evaluadas."
    )


class Devoluciones(BaseModel):
    """KPI: metricas de devoluciones."""

    volumen: int = Field(..., ge=0, description="Volumen total de devoluciones.")
    tasa_porcentaje: float = Field(
        ..., ge=0.0, le=100.0, description="Tasa de devoluciones respecto al total de envios."
    )


class ExecutiveKPIs(BaseModel):
    """Registro completo de KPIs ejecutivos, equivalente al contrato
    definido en ``CONTEXT-trackflow-briefing.es.md`` y ``PIPELINE_DESIGN.md``."""

    fecha_reporte: str = Field(
        ..., description="Fecha del reporte (constraint unico para upsert)."
    )
    id_corrida: str = Field(
        ..., description="Identificador unico de la corrida (hash de eventos)."
    )
    timestamp: str = Field(
        ..., description="Timestamp ISO 8601 de cuando se calcularon los KPIs."
    )
    periodo: str = Field(
        ..., description="Periodo semanal cubierto por el reporte."
    )
    volumen_envios: VolumenEnvios = Field(
        ..., description="Volumen de envios (total y desglose por almacen)."
    )
    tasa_entrega_tiempo: TasaEntregaTiempo = Field(
        ..., description="Tasa de entrega a tiempo (on-time delivery)."
    )
    devoluciones: Devoluciones = Field(
        ..., description="Metricas de devoluciones (volumen y tasa)."
    )

    class Config:
        json_schema_extra = {
            "example": {
                "fecha_reporte": "2026-09-03",
                "id_corrida": "86d14273cdbe",
                "timestamp": "2026-09-03T01:57:11.768269+00:00",
                "periodo": "2026-09-03",
                "volumen_envios": {
                    "total": 2,
                    "por_almacen": {"los-angeles": 1, "zaragoza": 1},
                },
                "tasa_entrega_tiempo": {
                    "porcentaje": 50.0,
                    "entregas_on_time": 1,
                    "entregas_totales": 2,
                },
                "devoluciones": {
                    "volumen": 2,
                    "tasa_porcentaje": 100.0,
                },
            }
        }


class KPIListResponse(BaseModel):
    """Respuesta paginada de registros de KPIs ejecutivos."""

    registros: list[ExecutiveKPIs] = Field(
        ..., description="Lista de registros de KPIS."
    )
    total: int = Field(..., ge=0, description="Cantidad total de registros disponibles.")

    class Config:
        json_schema_extra = {
            "example": {
                "registros": [
                    {
                        "fecha_reporte": "2026-09-03",
                        "id_corrida": "86d14273cdbe",
                        "timestamp": "2026-09-03T01:57:11.768269+00:00",
                        "periodo": "2026-09-03",
                        "volumen_envios": {
                            "total": 2,
                            "por_almacen": {"los-angeles": 1, "zaragoza": 1},
                        },
                        "tasa_entrega_tiempo": {
                            "porcentaje": 50.0,
                            "entregas_on_time": 1,
                            "entregas_totales": 2,
                        },
                        "devoluciones": {
                            "volumen": 2,
                            "tasa_porcentaje": 100.0,
                        },
                    }
                ],
                "total": 1,
            }
        }