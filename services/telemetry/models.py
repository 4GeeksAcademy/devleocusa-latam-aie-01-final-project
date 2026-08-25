"""Pydantic models for telemetry event ingestion."""

from __future__ import annotations

from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field


class TelemetryEvent(BaseModel):
    """A single telemetry event payload.

    This is the canonical envelope that all telemetry producers must emit.
    """

    eventId: UUID | str
    timestamp: str  # ISO 8601
    sessionId: str
    userId: str | None = None
    event_type: str
    schemaVersion: str
    requestId: str
    properties: dict[str, Any] = Field(default_factory=dict)


class TelemetryBatch(BaseModel):
    """Wrapper for a batch of telemetry events.

    Expected request body: { "events": [...] }
    """

    events: list[TelemetryEvent]