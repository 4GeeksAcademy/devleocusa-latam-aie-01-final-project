#!/usr/bin/env python
"""
TrackFlow — Pipeline de Telemetría (Fase 2 & 3)
=================================================

Extrae eventos de telemetría de los almacenes de Los Ángeles y Zaragoza,
los transforma en KPIs ejecutivos (volumen de envíos, tasa de entrega a
tiempo, métricas de devoluciones) y carga los resultados con **idempotencia**
mediante una estrategia de upsert.

Resiliencia:
  - Las tareas de extracción y carga tienen retries=3 / retry_delay_seconds=10
    para absorber fallos transitorios de red de los almacenes.

Cache:
  - La tarea de transformación emplea cache_key_fn + cache_expiration=1h
    para evitar recalcular KPIs si el flow se dispara varias veces en la
    misma hora, garantizando consistencia en el reporte semanal del CEO.

Idempotencia:
  - La carga simula un upsert basado en un constraint único
    (fecha_reporte + id_corrida) para que el pipeline pueda ejecutarse
    N veces sobre los mismos datos sin generar duplicados.

Ejecución:
    python data/pipelines/pipeline.py
"""

from __future__ import annotations

import os
import json
import logging
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from typing import Any

from prefect import flow, task
from prefect.logging import get_run_logger

# ---------------------------------------------------------------------------
# Configuración de entorno
# ---------------------------------------------------------------------------

PIPELINE_ENV = os.getenv("PIPELINE_ENV", "development")
RAW_DATA_DIR = os.getenv("RAW_DATA_DIR", "data/raw")
PROCESSED_DATA_DIR = os.getenv("PROCESSED_DATA_DIR", "data/process")
TARGET_TABLE = os.getenv("TARGET_TABLE", "executive_kpis")
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO")

logging.basicConfig(
    level=getattr(logging, LOG_LEVEL.upper(), logging.INFO),
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger("trackflow.pipeline")

# ---------------------------------------------------------------------------
# Simulaciones de datos de entrada
# ---------------------------------------------------------------------------

_SAMPLE_EVENTS: list[dict[str, Any]] = [
    {
        "event_id": "ev-001",
        "timestamp": "2026-09-03T08:15:00Z",
        "warehouse": "los-angeles",
        "event_type": "shipment.created",
        "payload": {"shipment_id": "SHP-LA-001", "destination": "CA"},
    },
    {
        "event_id": "ev-002",
        "timestamp": "2026-09-03T08:20:00Z",
        "warehouse": "zaragoza",
        "event_type": "shipment.created",
        "payload": {"shipment_id": "SHP-ZA-001", "destination": "Madrid"},
    },
    {
        "event_id": "ev-003",
        "timestamp": "2026-09-03T09:00:00Z",
        "warehouse": "los-angeles",
        "event_type": "shipment.delivered",
        "payload": {"shipment_id": "SHP-LA-001", "on_time": True},
    },
    {
        "event_id": "ev-004",
        "timestamp": "2026-09-03T09:10:00Z",
        "warehouse": "zaragoza",
        "event_type": "shipment.delivered",
        "payload": {"shipment_id": "SHP-ZA-001", "on_time": False},
    },
    {
        "event_id": "ev-005",
        "timestamp": "2026-09-03T09:30:00Z",
        "warehouse": "los-angeles",
        "event_type": "return.initiated",
        "payload": {"return_id": "RET-LA-001", "reason": "wrong_item"},
    },
    {
        "event_id": "ev-006",
        "timestamp": "2026-09-03T10:00:00Z",
        "warehouse": "zaragoza",
        "event_type": "return.completed",
        "payload": {"return_id": "RET-ZA-001", "condition": "damaged"},
    },
]

# ---------------------------------------------------------------------------
# Helper — Cache key para la tarea de transformación
# ---------------------------------------------------------------------------


def _kpis_cache_key(
    task_ctx: Any,
    inputs: dict[str, Any],
) -> str:
    """
    Genera un hash determinista a partir de los IDs de eventos ordenados.

    ``task_ctx`` lo proporciona Prefect (TaskRunContext).
    ``inputs`` contiene los argumentos de la tarea bajo la clave ``eventos``.

    Si el conjunto de eventos es el mismo, el cache key será idéntico y
    Prefect reutilizará el resultado cacheado durante 1 hora, evitando
    recalcular KPIs innecesariamente.
    """
    eventos = inputs.get("eventos", [])
    ids_ordenados = sorted(e["event_id"] for e in eventos)
    raw = ",".join(ids_ordenados)
    return sha256(raw.encode("utf-8")).hexdigest()


# ---------------------------------------------------------------------------
# Tarea 1 — Extracción (con retries)
# ---------------------------------------------------------------------------


@task(
    name="extraer_telemetria",
    description="Simula la lectura de eventos de telemetría desde la fuente.",
    retries=3,
    retry_delay_seconds=10,
    # Justificación: Los almacenes de Los Ángeles y Zaragoza operan con
    # sistemas independientes y conexiones de red que no siempre son
    # estables. Con 3 reintentos y 10s de espera entre ellos absorbemos
    # fallos transitorios de red sin intervención manual, evitando así
    # que el equipo de tecnología se entere de los fallos por WhatsApp.
)
def extraer_telemetria() -> list[dict[str, Any]]:
    """
    Lee los eventos de telemetría de los almacenes.

    En producción esto conectaría con el sistema de eventos (Kafka / API /
    base de datos). En esta fase simulamos la lectura con datos de ejemplo.
    """
    logger = get_run_logger()
    logger.info(
        "Extrayendo eventos de telemetría desde %s (entorno: %s)...",
        RAW_DATA_DIR,
        PIPELINE_ENV,
    )

    eventos = _SAMPLE_EVENTS.copy()
    logger.info("Extraídos %d eventos correctamente.", len(eventos))
    return eventos


# ---------------------------------------------------------------------------
# Tarea 2 — Transformación (con caché)
# ---------------------------------------------------------------------------


@task(
    name="transformar_a_kpis",
    description="Procesa los eventos en KPIs ejecutivos.",
    cache_key_fn=_kpis_cache_key,
    cache_expiration=timedelta(hours=1),
    # Justificación: La caché evita recalcular KPIs si el flow se dispara
    # varias veces dentro de la misma hora. Esto reduce carga computacional
    # y garantiza consistencia en los datos que ve Daniel Espinoza en su
    # reporte semanal automatizado, evitando métricas inconsistentes
    # entre ejecuciones.
)
def transformar_a_kpis(eventos: list[dict[str, Any]]) -> dict[str, Any]:
    """
    Transforma los eventos brutos en los KPIS que exige la Dirección:

      - Volumen de envíos (totales y por almacén)
      - Tasa de entrega a tiempo (on-time delivery rate)
      - Métricas de devoluciones (volumen, tasa sobre envíos)
    """
    logger = get_run_logger()
    logger.info("Transformando %d eventos en KPIs...", len(eventos))

    # ── Clasificar eventos ────────────────────────────────────────────
    envios_creados = [
        e for e in eventos if e["event_type"] == "shipment.created"
    ]
    envios_entregados = [
        e for e in eventos if e["event_type"] == "shipment.delivered"
    ]
    devoluciones = [
        e for e in eventos if e["event_type"].startswith("return.")
    ]

    # ── Volumen de envíos ─────────────────────────────────────────────
    volumen_total = len(envios_creados)

    envios_por_almacen: dict[str, int] = {}
    for e in envios_creados:
        w = e["warehouse"]
        envios_por_almacen[w] = envios_por_almacen.get(w, 0) + 1

    # ── Tasa de entrega a tiempo ──────────────────────────────────────
    entregas_totales = len(envios_entregados)
    entregas_on_time = sum(
        1 for e in envios_entregados if e["payload"].get("on_time")
    )
    tasa_entrega_tiempo = (
        (entregas_on_time / entregas_totales * 100)
        if entregas_totales > 0
        else 0.0
    )

    # ── Métricas de devoluciones ───────────────────────────────────────
    devoluciones_volumen = len(devoluciones)
    tasa_devoluciones = (
        (devoluciones_volumen / volumen_total * 100)
        if volumen_total > 0
        else 0.0
    )

    # ── Construir KPIs (incluye clave única para idempotencia) ────────
    id_corrida = sha256(
        str(tuple(sorted(e["event_id"] for e in eventos))).encode()
    ).hexdigest()[:12]

    kpis: dict[str, Any] = {
        "fecha_reporte": "2026-09-03",  # constraint único para el upsert
        "id_corrida": id_corrida,        # hash de eventos como segunda clave
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "periodo": "2026-09-03",
        "volumen_envios": {
            "total": volumen_total,
            "por_almacen": envios_por_almacen,
        },
        "tasa_entrega_tiempo": {
            "porcentaje": round(tasa_entrega_tiempo, 2),
            "entregas_on_time": entregas_on_time,
            "entregas_totales": entregas_totales,
        },
        "devoluciones": {
            "volumen": devoluciones_volumen,
            "tasa_porcentaje": round(tasa_devoluciones, 2),
        },
    }

    logger.info("KPIs calculados: %s", json.dumps(kpis, indent=2))
    return kpis


# ---------------------------------------------------------------------------
# Tarea 3 — Carga con idempotencia (upsert simulado)
# ---------------------------------------------------------------------------


@task(
    name="cargar_resultados",
    description="Prepara la escritura de los KPIs en la tabla destino con upsert.",
    retries=3,
    retry_delay_seconds=10,
    # Justificación: Al igual que en extracción, la conexión a la base de
    # datos destino puede presentar cortes transitorios. Los reintentos
    # automatizados evitan que un pico de latencia detenga el pipeline.
)
def cargar_resultados(kpis: dict[str, Any]) -> dict[str, Any]:
    """
    Prepara los KPIs para su inserción en la tabla ``executive_kpis``
    utilizando una estrategia de **upsert**.

    La idempotencia se garantiza mediante un constraint único compuesto
    por ``fecha_reporte`` + ``id_corrida``. Si el pipeline se ejecuta dos
    veces sobre los mismos datos, la segunda escritura será un UPDATE
    (no un INSERT duplicado), asegurando que el volumen de envíos y las
    métricas de devoluciones jamás se dupliquen en la base de datos.

    En producción esto se traduciría en:
        INSERT INTO executive_kpis (...)
        VALUES (...)
        ON CONFLICT (fecha_reporte, id_corrida)
        DO UPDATE SET ... ;
    """
    logger = get_run_logger()
    logger.info("Preparando carga hacia tabla '%s'...", TARGET_TABLE)

    fecha_reporte = kpis.get("fecha_reporte", "unknown")
    id_corrida = kpis.get("id_corrida", "unknown")

    registro: dict[str, Any] = {
        "table": TARGET_TABLE,
        "data": kpis,
        "loaded_at": datetime.now(timezone.utc).isoformat(),
        "status": "ready",
        # ── Estrategia de idempotencia: upsert ────────────────────────
        "upsert_constraint": {
            "primary_key": ["fecha_reporte", "id_corrida"],
            "values": {
                "fecha_reporte": fecha_reporte,
                "id_corrida": id_corrida,
            },
            "strategy": (
                "INSERT INTO executive_kpis (...) "
                "VALUES (...) "
                f"ON CONFLICT (fecha_reporte, id_corrida) "
                "DO UPDATE SET "
                "  timestamp = EXCLUDED.timestamp,"
                "  volumen_envios = EXCLUDED.volumen_envios,"
                "  tasa_entrega_tiempo = EXCLUDED.tasa_entrega_tiempo,"
                "  devoluciones = EXCLUDED.devoluciones,"
                "  loaded_at = EXCLUDED.loaded_at;"
            ),
        },
    }

    logger.info("UPSERT simulado sobre (%s, %s)", fecha_reporte, id_corrida)
    logger.info(
        "Registro preparado para inserción/actualización: %s",
        json.dumps(registro, indent=2),
    )
    return registro


# ---------------------------------------------------------------------------
# Tarea 4 — Notificación de estado (opcional / no crítica)
# ---------------------------------------------------------------------------


@task(
    name="notificar_estado",
    description="Snapshot de validación o notificación de estado del pipeline.",
)
def notificar_estado(resultado_carga: dict[str, Any]) -> str:
    """
    Tarea **no crítica**: genera un snapshot de validación con el estado
    del pipeline. Si falla, el flujo principal continúa porque se invoca
    con ``return_state=True``.
    """
    logger = get_run_logger()
    logger.info("Generando snapshot de validación...")

    notificacion: dict[str, Any] = {
        "tipo": "pipeline_snapshot",
        "estado": "completado",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "registros_cargados": resultado_carga.get("status") == "ready",
        "tabla_destino": resultado_carga.get("table"),
        "upsert_constraint": resultado_carga.get(
            "upsert_constraint", {}
        ).get("primary_key"),
    }

    # ⚠️ Simulación de fallo si la variable de entorno NOTIFY_FAIL está activa
    if os.getenv("NOTIFY_FAIL", "").lower() in ("1", "true", "yes"):
        msg = "Servicio de notificaciones no disponible (simulado)."
        logger.error(msg)
        raise RuntimeError(msg)

    logger.info("Snapshot generado: %s", json.dumps(notificacion, indent=2))
    return "notificacion_enviada"


# ---------------------------------------------------------------------------
# Flujo principal
# ---------------------------------------------------------------------------


@flow(
    name="trackflow_pipeline_telemetria",
    description="Pipeline ETL de telemetría TrackFlow — Fase 2 & 3.",
    log_prints=True,
)
def trackflow_pipeline_telemetria() -> dict[str, Any]:
    """
    Orquestador principal del pipeline de telemetría.

    Pipeline:
      1. extraer_telemetria  →  eventos brutos (con retries)
      2. transformar_a_kpis  →  KPIs ejecutivos (con caché de 1h)
      3. cargar_resultados   →  registro con upsert (con retries)
      4. notificar_estado    →  snapshot NO crítico (return_state=True)
    """
    from prefect.context import get_run_context

    logger = get_run_logger()
    hora_inicio = datetime.now(timezone.utc)

    logger.info("═══ Iniciando pipeline de telemetría TrackFlow ═══")
    logger.info(
        "Entorno: %s | Tabla destino: %s | Hora inicio: %s",
        PIPELINE_ENV,
        TARGET_TABLE,
        hora_inicio.isoformat(),
    )

    # ── Extracción ────────────────────────────────────────────────────
    eventos = extraer_telemetria()
    registros_extraidos = len(eventos)
    logger.info("Extracción completada: %d eventos.", registros_extraidos)

    # ── Transformación ────────────────────────────────────────────────
    kpis = transformar_a_kpis(eventos)
    logger.info("Transformación completada.")

    # ── Carga ─────────────────────────────────────────────────────────
    resultado = cargar_resultados(kpis)
    logger.info("Carga preparada (estrategia upsert).")

    # ── Notificación NO crítica (return_state=True) ──────────────────
    estado_notificacion = notificar_estado.with_options(retries=0)(
        resultado, return_state=True
    )

    errores: list[str] = []

    if estado_notificacion.is_completed():
        logger.info("Notificación enviada correctamente.")
    else:
        msg = str(estado_notificacion.message or "Error desconocido en notificación")
        logger.warning(
            "La tarea de notificación falló (razón: %s) — "
            "el pipeline principal continúa sin interrupción.",
            msg,
        )
        errores.append(msg)

    hora_fin = datetime.now(timezone.utc)
    duracion = (hora_fin - hora_inicio).total_seconds()
    estado_final = "Completed"

    # ── Logging de metadata de la corrida ─────────────────────────────
    logger.info("═══ Pipeline finalizado ═══")
    logger.info("Metadata de la corrida:")
    logger.info("  Hora inicio        : %s", hora_inicio.isoformat())
    logger.info("  Hora fin           : %s", hora_fin.isoformat())
    logger.info("  Duración (seg)     : %.2f", duracion)
    logger.info("  Registros extraídos: %d", registros_extraidos)
    logger.info("  KPIs calculados    : %d", 1)
    logger.info("  Estado final       : %s", estado_final)
    logger.info("  Cache (transform)  : activa (1 hora)")
    logger.info("  Idempotencia       : upsert sobre (fecha_reporte, id_corrida)")

    # ── Metadata incrustada en el resultado para trazabilidad ─────────
    ctx = get_run_context()
    flow_run_id = ctx.flow_run.id if ctx.flow_run else "N/A"
    resultado["_metadata"] = {
        "hora_inicio": hora_inicio.isoformat(),
        "hora_fin": hora_fin.isoformat(),
        "duracion_segundos": round(duracion, 2),
        "registros_extraidos": registros_extraidos,
        "estado_final": estado_final,
        "flow_run_id": flow_run_id,
        "errores": errores,
    }

    return resultado


# ---------------------------------------------------------------------------
# Ejecución CLI
# ---------------------------------------------------------------------------

if __name__ == "__main__":
    trackflow_pipeline_telemetria()
