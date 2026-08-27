"""FastAPI router for telemetry event ingestion.

Endpoints:
    POST /telemetry/events  —  Receive, validate, and persist a batch
                               of telemetry events into Supabase.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from fastapi import APIRouter
from pydantic import ValidationError

from telemetry.models import TelemetryEvent

logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(tags=["telemetry"])


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