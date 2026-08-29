"""FastAPI router for telemetry event ingestion and reporting.

Endpoints:
    POST /telemetry/events  —  Receive, validate, and persist a batch
                               of telemetry events into Supabase.
    GET  /telemetry/report  —  Aggregated operational metrics for a
                               given time window (cached for 60 s).
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Query
from pydantic import ValidationError

from telemetry.models import TelemetryEvent

logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(tags=["telemetry"])

# Shared in-memory cache imported from the api service layer
from src.cache import TTLCache  # noqa: E402

_report_cache = TTLCache(ttl_seconds=60)


# ──────────────────────────────────────────────
# Supabase client (lazy initialisation)
# ──────────────────────────────────────────────

def _get_supabase_client():
    """Create and return a Supabase client using environment credentials."""
    from supabase import create_client

    supabase_url = os.environ.get("SUPABASE_URL")
    supabase_key = os.environ.get("SUPABASE_SERVICE_KEY")

    if not supabase_url or not supabase_key:
        raise RuntimeError(
            "SUPABASE_URL and SUPABASE_SERVICE_KEY must be set in the "
            "environment to persist telemetry events."
        )

    return create_client(supabase_url, supabase_key)


# ──────────────────────────────────────────────
# POST /telemetry/events
# ──────────────────────────────────────────────


@router.post("/events", status_code=200)
def receive_events(body: dict[str, Any]) -> dict[str, int]:
    """Receive, validate, and persist a batch of telemetry events.

    Each event is validated individually via
    ``TelemetryEvent.model_validate()`` so that a single malformed
    event does **not** cancel the whole batch.  Valid events are
    bulk-inserted into the ``telemetry_events`` table using the official
    Supabase Python client in one operation.
    """
    raw_events: list[Any] = body.get("events", [])
    received = len(raw_events)

    valid_rows: list[dict[str, Any]] = []
    rejected = 0

    # ── 1. Validate each event individually ──────────────────────────
    for raw in raw_events:
        if not isinstance(raw, dict):
            rejected += 1
            logger.warning(
                "Telemetry event rejected — not a dict: %s",
                type(raw).__name__,
            )
            continue

        try:
            event = TelemetryEvent.model_validate(raw)
        except ValidationError as exc:
            rejected += 1
            logger.warning(
                "Telemetry event rejected — validation error: %s",
                exc.errors(include_url=False),
            )
            continue

        # Map the validated Pydantic model to a row for the
        # ``telemetry_events`` table.
        row: dict[str, Any] = {
            "id": str(event.eventId),
            "event_type": event.event_type,
            "timestamp": event.timestamp,
            "payload": event.properties,
            "tags": {
                "sessionId": event.sessionId,
                "userId": event.userId,
                "requestId": event.requestId,
                "schemaVersion": event.schemaVersion,
            },
        }
        valid_rows.append(row)

    # ── 2. Bulk insert via Supabase Python client ────────────────────
    stored = 0

    if valid_rows:
        try:
            client = _get_supabase_client()
            response = client.table("telemetry_events").insert(valid_rows).execute()
            stored = len(response.data) if response.data else len(valid_rows)

            logger.info(
                "Telemetry batch persisted — received=%d stored=%d rejected=%d",
                received,
                stored,
                rejected,
            )
        except Exception:
            logger.exception("Bulk insert into telemetry_events failed")
            # If the entire batch insert fails, none were stored and all
            # previously "valid" events count toward the rejected total.
            stored = 0
            rejected = received

    # ── 3. Response ──────────────────────────────────────────────────
    return {
        "received": received,
        "stored": stored,
        "rejected": rejected,
    }


# ───────────────────────────────────────────────────────────────────
# Helper: fetch telemetry rows from Supabase within a time window
# ───────────────────────────────────────────────────────────────────

def _fetch_events(start: datetime, end: datetime) -> list[dict[str, Any]]:
    """Return all ``telemetry_events`` rows whose *timestamp* falls
    between **start** and **end** (both UTC-aware).

    Connects via psycopg2 using the ``SQL_URL`` environment variable
    (same Postgres connection string used by the rest of the project).
    """
    import psycopg2
    import psycopg2.extras

    sql_url = os.environ.get("SQL_URL")
    if not sql_url:
        raise RuntimeError(
            "SQL_URL must be set in the environment to fetch telemetry events."
        )

    conn = psycopg2.connect(sql_url)
    try:
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute(
                """
                SELECT *
                FROM telemetry_events
                WHERE timestamp >= %s AND timestamp <= %s
                ORDER BY timestamp ASC
                """,
                (start, end),
            )
            rows = cur.fetchall()
            # RealDictCursor rows are dict-like; convert to plain dicts
            return [dict(row) for row in rows]
    finally:
        conn.close()


# ───────────────────────────────────────────────────────────────────
# GET /telemetry/report
# ───────────────────────────────────────────────────────────────────


@router.get("/report")
def get_report(
    start_date: str | None = Query(
        default=None,
        description="Start of the time window (ISO 8601, UTC). "
        "Defaults to 7 days ago.",
    ),
    end_date: str | None = Query(
        default=None,
        description="End of the time window (ISO 8601, UTC). "
        "Defaults to now.",
    ),
) -> dict[str, Any]:
    """Return aggregated operational metrics for the given time window.

    The result is cached in memory for **60 seconds** based on the
    requested date range.  The cache is skipped automatically on
    expiry, ensuring subsequent requests within the TTL return the
    same data without re-computation.
    """
    # ── 1. Resolve date boundaries (UTC) ────────────────────────────────
    now = datetime.now(timezone.utc)

    if end_date is not None:
        _end = datetime.fromisoformat(end_date).replace(tzinfo=timezone.utc)
    else:
        _end = now

    if start_date is not None:
        _start = datetime.fromisoformat(start_date).replace(tzinfo=timezone.utc)
    else:
        _start = _end - timedelta(days=7)

    # ── 2. Cache lookup ─────────────────────────────────────────────────
    cache_key = f"{_start.isoformat()}/{_end.isoformat()}"
    cached = _report_cache.get(cache_key)
    if cached is not None:
        logger.debug("Report cache HIT for window %s", cache_key)
        return cached  # type: ignore[return-value]

    logger.debug("Report cache MISS for window %s", cache_key)

    # ── 3. Fetch raw data from Supabase ─────────────────────────────────
    raw_rows = _fetch_events(_start, _end)

    if not raw_rows:
        result: dict[str, Any] = {
            "period": {"from": _start.isoformat(), "to": _end.isoformat()},
            "metrics": {"events_per_day": [], "error_rate_by_type": []},
        }
        _report_cache.set(cache_key, result)
        return result

    # ── 4. Build DataFrame and compute metrics ──────────────────────────
    import pandas as pd

    from telemetry.analysis import error_rate_by_type, events_per_day

    df = pd.DataFrame(raw_rows)

    events_per_day_result = events_per_day(df)
    error_rate_by_type_result = error_rate_by_type(df)

    result = {
        "period": {"from": _start.isoformat(), "to": _end.isoformat()},
        "metrics": {
            "events_per_day": events_per_day_result,
            "error_rate_by_type": error_rate_by_type_result,
        },
    }

    _report_cache.set(cache_key, result)
    return result