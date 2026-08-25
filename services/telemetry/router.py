"""FastAPI router for telemetry event ingestion.

Endpoints:
    POST /telemetry/events  —  Receive a batch of telemetry events.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter

from .models import TelemetryBatch

logger = logging.getLogger("trackflow.telemetry")

router = APIRouter(tags=["telemetry"])


@router.post("/events", status_code=200)
async def receive_events(batch: TelemetryBatch) -> dict[str, int]:
    """Receive and log a batch of telemetry events.

    This is a stub endpoint — it validates, logs, and acknowledges
    the events without persisting them to any database.
    """
    total = len(batch.events)
    event_types = {e.event_type for e in batch.events}

    logger.info(
        "Telemetry batch received — total=%d, event_types=%s",
        total,
        sorted(event_types),
    )

    for event in batch.events:
        logger.debug(
            "Telemetry event — eventId=%s event_type=%s sessionId=%s",
            event.eventId,
            event.event_type,
            event.sessionId,
        )

    return {"received": total}