#!/usr/bin/env python3
"""Telemetry KPI daily pipeline — standalone entry point.

Orchestrates the extraction, transformation, and load of daily telemetry
metrics from Supabase into operational KPIs.

This module is invoked by ``scripts/nightly_export.py`` via subprocess::

    python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run --no-prefect

Design invariants:
    - **Zero FastAPI dependencies** — pure CLI / cron background process.
    - Data source: ``telemetry_events`` table in Supabase (PostgreSQL).
    - CSV files in ``data/raw/`` are audit dumps only — never read here.
    - Prefect orchestration is optional (``--no-prefect`` bypasses it).

Usage::

    # With Prefect orchestration (default)
    python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run

    # Bypass Prefect — imperative execution
    python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run --no-prefect

    # Explicit target date
    TARGET_DATE=2026-09-07 python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run --no-prefect
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Path bootstrap ────────────────────────────────────────────────────────
# Ensure ``src.*`` is importable when running as a module from project root.

ROOT_DIR: Path = Path(__file__).resolve().parents[5]  # up to project root
API_DIR: Path = ROOT_DIR / "services" / "api"

for _p in (API_DIR,):
    _p_str = str(_p)
    if _p_str not in sys.path:
        sys.path.insert(0, _p_str)

# Load .env if present (idempotent)
try:
    from src.env_loader import load_env_if_available

    load_env_if_available()
except ImportError:
    pass

# ── Logging ───────────────────────────────────────────────────────────────

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("telemetry_kpi_daily")

# ── Constants ─────────────────────────────────────────────────────────────

RAW_DIR: Path = ROOT_DIR / "data" / "raw"
PROCESS_DIR: Path = ROOT_DIR / "data" / "process"


# ═══════════════════════════════════════════════════════════════════════════
# 1. TARGET DATE RESOLUTION
# ═══════════════════════════════════════════════════════════════════════════


def resolve_target_date() -> date:
    """Return the target date for this pipeline run.

    Reads the ``TARGET_DATE`` environment variable (injected by the parent
    ``nightly_export.py`` process).  Falls back to yesterday (UTC) when
    unset or malformed.
    """
    raw: str | None = os.environ.get("TARGET_DATE")
    if raw:
        try:
            return date.fromisoformat(raw.strip())
        except ValueError:
            logger.warning(
                "Invalid TARGET_DATE=%r — falling back to yesterday (UTC).",
                raw,
            )
    return datetime.now(timezone.utc).date() - timedelta(days=1)


# ═══════════════════════════════════════════════════════════════════════════
# 2. DATA EXTRACTION — Supabase (PostgreSQL)
# ═══════════════════════════════════════════════════════════════════════════


def extract_events(target: date) -> list[dict[str, Any]]:
    """Fetch telemetry events for *target* date from Supabase.

    Connects via ``SQL_URL`` using psycopg2 (same pattern as the
    telemetry router).  The query filters by ``timestamp`` within the
    target day boundaries (UTC).

    **This is the ONLY data source.**  CSV files in ``data/raw/`` are
    never read.

    Parameters
    ----------
    target:
        Calendar date to extract events for.

    Returns
    -------
    List of event dictionaries with keys: ``id``, ``event_type``,
    ``timestamp``, ``payload`` (JSONB → dict), ``tags`` (JSONB → dict).

    Raises
    ------
    RuntimeError
        If ``SQL_URL`` is not set in the environment.
    """
    sql_url: str | None = os.environ.get("SQL_URL")
    if not sql_url:
        raise RuntimeError(
            "SQL_URL environment variable is not set. "
            "Cannot query telemetry_events."
        )

    day_start: datetime = datetime.combine(
        target, datetime.min.time(), tzinfo=timezone.utc
    )
    day_end: datetime = day_start + timedelta(days=1)

    logger.info(
        "Extracting telemetry events for %s (UTC %s → %s)…",
        target.isoformat(),
        day_start.isoformat(),
        day_end.isoformat(),
    )

    import psycopg2
    import psycopg2.extras

    conn = psycopg2.connect(sql_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT id, event_type, timestamp, payload, tags
                FROM telemetry_events
                WHERE timestamp >= %s AND timestamp < %s
                ORDER BY timestamp ASC
                """,
                (day_start, day_end),
            )
            rows: list[dict[str, Any]] = cur.fetchall()

        # psycopg2 returns jsonb columns as Python dicts — convert to plain dicts
        events: list[dict[str, Any]] = [dict(row) for row in rows]
        logger.info("Extracted %d telemetry events.", len(events))
        return events

    finally:
        conn.close()


# ═══════════════════════════════════════════════════════════════════════════
# 3. TRANSFORMATION — KPI Calculations
# ═══════════════════════════════════════════════════════════════════════════
#
# Each KPI subflow is a pure function: events → dict.
# Prefect wrappers are applied conditionally via ``--no-prefect``.
#
# The event schema in ``payload`` (JSONB) varies by ``event_type``:
#   - shipment.created   → { warehouse, destination, weight_kg, ... }
#   - shipment.delivered → { warehouse, destination, on_time, ... }
#   - shipment.returned  → { warehouse, reason, ... }
#   - payment.processed  → { amount, currency, method, ... }
#   - feedback.submitted → { rating, comment, ... }
# ═══════════════════════════════════════════════════════════════════════════


def _extract_payload(event: dict[str, Any]) -> dict[str, Any]:
    """Safely extract the ``payload`` dict from an event row."""
    payload = event.get("payload")
    if isinstance(payload, str):
        try:
            return json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return {}
    return payload if isinstance(payload, dict) else {}


def calculate_shipping_volume(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute total shipping volume and per-warehouse breakdown.

    Counts ``shipment.created`` events grouped by warehouse.

    Returns
    -------
    ``{"total": int, "por_almacen": {warehouse: count, ...}}``
    """
    created = [e for e in events if e.get("event_type") == "shipment.created"]
    total: int = len(created)

    by_warehouse: dict[str, int] = defaultdict(int)
    for e in created:
        payload = _extract_payload(e)
        warehouse: str = payload.get("warehouse", "unknown")
        by_warehouse[warehouse] += 1

    result = {"total": total, "por_almacen": dict(by_warehouse)}
    logger.info("Shipping volume: total=%d, warehouses=%d", total, len(by_warehouse))
    return result


def calculate_on_time_delivery_rate(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute on-time delivery rate from ``shipment.delivered`` events.

    Returns
    -------
    ``{"total_delivered": int, "on_time": int, "rate": float}``
    """
    delivered = [e for e in events if e.get("event_type") == "shipment.delivered"]
    total_delivered: int = len(delivered)

    on_time: int = 0
    for e in delivered:
        payload = _extract_payload(e)
        if payload.get("on_time") is True:
            on_time += 1

    rate: float = (on_time / total_delivered * 100) if total_delivered > 0 else 0.0

    result = {
        "total_delivered": total_delivered,
        "on_time": on_time,
        "rate": round(rate, 2),
    }
    logger.info(
        "On-time delivery: %d/%d (%.1f%%)", on_time, total_delivered, rate,
    )
    return result


def calculate_operational_cost(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute estimated operational cost from ``payment.processed`` events.

    Returns
    -------
    ``{"total_cost": float, "count": int, "avg_cost": float}``
    """
    payments = [e for e in events if e.get("event_type") == "payment.processed"]
    total_cost: float = 0.0
    count: int = 0

    for e in payments:
        payload = _extract_payload(e)
        amount = payload.get("amount")
        if isinstance(amount, (int, float)):
            total_cost += float(amount)
            count += 1

    avg_cost: float = (total_cost / count) if count > 0 else 0.0

    result = {
        "total_cost": round(total_cost, 2),
        "count": count,
        "avg_cost": round(avg_cost, 2),
    }
    logger.info(
        "Operational cost: total=%.2f, count=%d, avg=%.2f",
        total_cost, count, avg_cost,
    )
    return result


def calculate_returns(events: list[dict[str, Any]]) -> dict[str, Any]:
    """Compute return metrics from ``shipment.returned`` events.

    Returns
    -------
    ``{"total_returns": int, "by_reason": {reason: count, ...}}``
    """
    returned = [e for e in events if e.get("event_type") == "shipment.returned"]
    total_returns: int = len(returned)

    by_reason: dict[str, int] = defaultdict(int)
    for e in returned:
        payload = _extract_payload(e)
        reason: str = payload.get("reason", "unspecified")
        by_reason[reason] += 1

    result = {
        "total_returns": total_returns,
        "by_reason": dict(by_reason),
    }
    logger.info("Returns: total=%d, reasons=%d", total_returns, len(by_reason))
    return result


def calculate_customer_satisfaction(
    events: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute customer satisfaction index from ``feedback.submitted`` events.

    Returns
    -------
    ``{"avg_rating": float, "count": int, "distribution": {rating: count}}``
    """
    feedbacks = [e for e in events if e.get("event_type") == "feedback.submitted"]
    total_ratings: float = 0.0
    count: int = 0
    distribution: dict[int, int] = defaultdict(int)

    for e in feedbacks:
        payload = _extract_payload(e)
        rating = payload.get("rating")
        if isinstance(rating, (int, float)):
            total_ratings += float(rating)
            count += 1
            distribution[int(rating)] += 1

    avg_rating: float = (total_ratings / count) if count > 0 else 0.0

    result = {
        "avg_rating": round(avg_rating, 2),
        "count": count,
        "distribution": dict(distribution),
    }
    logger.info(
        "Customer satisfaction: avg=%.2f, count=%d", avg_rating, count,
    )
    return result


# ═══════════════════════════════════════════════════════════════════════════
# 4. ASSEMBLY — Final KPI Record
# ═══════════════════════════════════════════════════════════════════════════


def assemble_executive_kpis(
    events: list[dict[str, Any]],
    target: date,
) -> dict[str, Any]:
    """Orchestrate all KPI subflows and assemble the final record.

    This is the main transformation entry point.  Each KPI subflow is
    called imperatively (no Prefect engine).

    Parameters
    ----------
    events:
        Raw telemetry events for the target date.
    target:
        The target date for this pipeline run.

    Returns
    -------
    Complete ``ExecutiveKPIs`` record ready for persistence.
    """
    logger.info("Assembling executive KPIs for %s…", target.isoformat())

    shipping_volume = calculate_shipping_volume(events)
    on_time_delivery = calculate_on_time_delivery_rate(events)
    operational_cost = calculate_operational_cost(events)
    returns = calculate_returns(events)
    customer_satisfaction = calculate_customer_satisfaction(events)

    kpi_record: dict[str, Any] = {
        "fecha_reporte": target.isoformat(),
        "volumen_envios": shipping_volume,
        "tasa_entrega_puntual": on_time_delivery,
        "costos_operativos": operational_cost,
        "devoluciones": returns,
        "satisfaccion_cliente": customer_satisfaction,
        "_metadata": {
            "pipeline": "telemetry_kpi_daily",
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "events_processed": len(events),
        },
    }

    logger.info("Executive KPIs assembled successfully.")
    return kpi_record


# ═══════════════════════════════════════════════════════════════════════════
# 5. LOAD — Persist Results
# ═══════════════════════════════════════════════════════════════════════════


def load_executive_kpis(kpi_record: dict[str, Any], target: date) -> Path:
    """Persist the assembled KPI record as a JSON file.

    Writes to ``data/process/telemetry_kpi_YYYY-MM-DD.json``.

    Parameters
    ----------
    kpi_record:
        The assembled executive KPI record.
    target:
        The target date (used for the output filename).

    Returns
    -------
    Path to the written JSON file.
    """
    PROCESS_DIR.mkdir(parents=True, exist_ok=True)
    output_path: Path = PROCESS_DIR / f"telemetry_kpi_{target.isoformat()}.json"

    with output_path.open("w", encoding="utf-8") as fh:
        json.dump(kpi_record, fh, indent=2, ensure_ascii=False, default=str)

    logger.info("KPI record persisted to %s", output_path)
    return output_path


# ═══════════════════════════════════════════════════════════════════════════
# 6. MAIN ORCHESTRATION
# ═══════════════════════════════════════════════════════════════════════════


def run_imperative(target: date) -> dict[str, Any]:
    """Execute the full pipeline imperatively (no Prefect).

    Steps:
        1. Extract events from Supabase.
        2. Transform: calculate all KPIs.
        3. Load: persist results to ``data/process/``.

    Returns
    -------
    The assembled KPI record.
    """
    logger.info("=== Running pipeline in IMPERATIVE mode (no Prefect) ===")

    # Step 1: Extract
    events = extract_events(target)

    if not events:
        logger.warning("No events found for %s. Generating empty KPI record.", target.isoformat())

    # Step 2: Transform
    kpi_record = assemble_executive_kpis(events, target)

    # Step 3: Load
    output_path = load_executive_kpis(kpi_record, target)
    kpi_record["_output_path"] = str(output_path)

    logger.info("=== Pipeline completed successfully ===")
    return kpi_record


def run_with_prefect(target: date) -> dict[str, Any]:
    """Execute the full pipeline with Prefect orchestration.

    This wraps each phase as a Prefect flow/task for observability,
    retries, and caching.

    Returns
    -------
    The assembled KPI record.
    """
    from prefect import flow

    @flow(name="telemetry_kpi_daily", log_prints=True)
    def _prefect_pipeline() -> dict[str, Any]:
        """Prefect-orchestrated daily telemetry KPI pipeline."""
        # Step 1: Extract
        events = extract_events(target)

        if not events:
            logger.warning(
                "No events found for %s. Generating empty KPI record.",
                target.isoformat(),
            )

        # Step 2: Transform
        kpi_record = assemble_executive_kpis(events, target)

        # Step 3: Load
        output_path = load_executive_kpis(kpi_record, target)
        kpi_record["_output_path"] = str(output_path)

        return kpi_record

    return _prefect_pipeline()


# ═══════════════════════════════════════════════════════════════════════════
# 7. CLI ENTRY POINT
# ═══════════════════════════════════════════════════════════════════════════


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Daily telemetry KPI pipeline.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run\n"
            "  python -m data.pipelines.src.pipelines.telemetry_kpi_daily.run --no-prefect\n"
        ),
    )
    parser.add_argument(
        "--no-prefect",
        action="store_true",
        default=False,
        help="Bypass Prefect orchestration and run imperatively.",
    )
    return parser.parse_args()


def main() -> None:
    """Entry point — orchestrates the full pipeline lifecycle.

    Catches all exceptions and exits with code 1 on failure so the
    parent process (nightly_export.py) can detect the error.
    """
    args = parse_args()
    target: date = resolve_target_date()

    logger.info("=== Telemetry KPI Daily Pipeline ===")
    logger.info("Target date: %s", target.isoformat())
    logger.info("Prefect mode: %s", "disabled" if args.no_prefect else "enabled")

    try:
        if args.no_prefect:
            kpi_record = run_imperative(target)
        else:
            kpi_record = run_with_prefect(target)

        logger.info("Pipeline completed for %s.", target.isoformat())
        logger.info(
            "KPI summary: shipping=%s, on_time=%s%%, cost=%s, returns=%s, satisfaction=%s",
            kpi_record.get("volumen_envios", {}).get("total", 0),
            kpi_record.get("tasa_entrega_puntual", {}).get("rate", 0),
            kpi_record.get("costos_operativos", {}).get("total_cost", 0),
            kpi_record.get("devoluciones", {}).get("total_returns", 0),
            kpi_record.get("satisfaccion_cliente", {}).get("avg_rating", 0),
        )

    except Exception:
        logger.exception(
            "Pipeline FAILED for date=%s",
            target.isoformat(),
        )
        sys.exit(1)


if __name__ == "__main__":
    main()
