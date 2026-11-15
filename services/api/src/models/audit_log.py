"""Append-only audit event model for sensitive TrackFlow operations."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal
from uuid import uuid4

from sqlmodel import Field, SQLModel


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class AuditLogEntry(SQLModel, table=True):
    """Immutable event record linked to the preceding event by SHA-256."""

    __tablename__ = "audit_log"

    id: str = Field(default_factory=lambda: str(uuid4()), primary_key=True)
    actor_id: str = Field(max_length=160, nullable=False, index=True)
    actor_type: str = Field(max_length=16, nullable=False)
    actor_name: str = Field(max_length=254, nullable=False)
    action: str = Field(max_length=100, nullable=False, index=True)
    resource_type: str = Field(max_length=100, nullable=False, index=True)
    resource_id: str = Field(max_length=200, nullable=False, index=True)
    occurred_at: datetime = Field(default_factory=_utcnow, nullable=False, index=True)
    source: str = Field(max_length=200, nullable=False)
    department: str = Field(max_length=100, nullable=False, index=True)
    country: str | None = Field(default=None, max_length=80)
    warehouse_id: str | None = Field(default=None, max_length=100)
    details_json: str = Field(default="{}", nullable=False)
    previous_hash: str = Field(max_length=64, nullable=False)
    event_hash: str = Field(max_length=64, nullable=False, unique=True)


ActorKind = Literal["human", "process"]
