"""Append-only audit logging, hash chaining and integrity verification."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import text
from sqlmodel import Session, select

from src.models.audit_log import AuditLogEntry, ActorKind

GENESIS_HASH = "0" * 64


def _canonical_event(payload: dict[str, Any]) -> bytes:
    return json.dumps(payload, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode("utf-8")


def _event_payload(entry: AuditLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor_id": entry.actor_id,
        "actor_type": entry.actor_type,
        "actor_name": entry.actor_name,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "occurred_at": entry.occurred_at.astimezone(timezone.utc).isoformat(),
        "source": entry.source,
        "department": entry.department,
        "country": entry.country,
        "warehouse_id": entry.warehouse_id,
        "details_json": entry.details_json,
        "previous_hash": entry.previous_hash,
    }


def append_event(
    session: Session,
    *,
    actor_id: str,
    actor_type: ActorKind,
    actor_name: str,
    action: str,
    resource_type: str,
    resource_id: str,
    source: str,
    department: str,
    country: str | None = None,
    warehouse_id: str | None = None,
    details: dict[str, Any] | None = None,
    occurred_at: datetime | None = None,
) -> AuditLogEntry:
    """Insert one event, serializing chain appends inside the DB transaction."""
    if (country is None) != (warehouse_id is None):
        raise ValueError("country and warehouse_id must be supplied together")
    if actor_type not in {"human", "process"}:
        raise ValueError("actor_type must be human or process")

    # PostgreSQL advisory lock serializes appends across API workers, preventing
    # two concurrent events from linking to the same previous hash.
    if session.bind is not None and session.bind.dialect.name == "postgresql":
        session.exec(text("SELECT pg_advisory_xact_lock(7281946201)"))

    # Locate the unique chain head (not simply the latest timestamp: timestamp
    # precision and delayed events must not change append order).
    referenced_hashes = select(AuditLogEntry.previous_hash)
    latest = session.exec(
        select(AuditLogEntry)
        .where(~AuditLogEntry.event_hash.in_(referenced_hashes))
        .limit(1)
    ).first()
    if latest is not None:
        genesis = session.exec(
            select(AuditLogEntry).where(AuditLogEntry.previous_hash == GENESIS_HASH)
        ).first()
        if genesis is None:
            raise RuntimeError("Existing audit chain has no genesis event; refusing to append")
        if not verify_chain(session)["valid"]:
            raise RuntimeError("Existing audit chain failed integrity verification; refusing to append")
    previous_hash = latest.event_hash if latest else GENESIS_HASH
    event = AuditLogEntry(
        actor_id=actor_id,
        actor_type=actor_type,
        actor_name=actor_name,
        action=action,
        resource_type=resource_type,
        resource_id=resource_id,
        occurred_at=occurred_at or datetime.now(timezone.utc),
        source=source[:200],
        department=department,
        country=country,
        warehouse_id=warehouse_id,
        details_json=json.dumps(details or {}, sort_keys=True, separators=(",", ":"), ensure_ascii=False),
        previous_hash=previous_hash,
        event_hash="pending",
    )
    event.event_hash = hashlib.sha256(_canonical_event(_event_payload(event))).hexdigest()
    session.add(event)
    session.flush()
    return event


def append_event_committed(**kwargs: Any) -> AuditLogEntry:
    """Persist an event in its own transaction for non-SQL operational stores.

    TinyDB-backed auth/users and carrier records cannot share a PostgreSQL
    transaction; callers must surface an audit failure and operators should
    reconcile the source mutation if this raises.
    """
    from src.database import get_engine

    with Session(get_engine()) as session:
        try:
            event = append_event(session, **kwargs)
            session.commit()
            session.refresh(event)
            return event
        except Exception:
            session.rollback()
            raise


def verify_chain(session: Session) -> dict[str, Any]:
    """Verify every event in stable append order and report the first mismatch."""
    entries = session.exec(select(AuditLogEntry)).all()
    next_by_previous: dict[str, AuditLogEntry] = {}
    for entry in entries:
        if entry.previous_hash in next_by_previous:
            return {"valid": False, "checked": 0, "event_id": entry.id, "reason": "chain_fork"}
        next_by_previous[entry.previous_hash] = entry

    expected_previous = GENESIS_HASH
    visited: set[str] = set()
    for index in range(len(entries)):
        entry = next_by_previous.get(expected_previous)
        if entry is None:
            return {"valid": False, "checked": index, "event_id": None, "reason": "broken_chain"}
        expected_hash = hashlib.sha256(_canonical_event(_event_payload(entry))).hexdigest()
        if entry.event_hash != expected_hash:
            return {"valid": False, "checked": index + 1, "event_id": entry.id, "reason": "event_hash_mismatch"}
        expected_previous = entry.event_hash
        visited.add(entry.event_hash)
    if len(visited) != len(entries):
        return {"valid": False, "checked": len(visited), "event_id": None, "reason": "orphaned_chain"}
    return {"valid": True, "checked": len(entries), "event_id": None, "reason": None}


def list_events(
    session: Session,
    *,
    actor: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    department: str | None = None,
    limit: int = 50,
    offset: int = 0,
) -> list[AuditLogEntry]:
    statement = select(AuditLogEntry)
    if actor:
        statement = statement.where(AuditLogEntry.actor_id == actor)
    if action:
        statement = statement.where(AuditLogEntry.action == action)
    if resource:
        statement = statement.where(AuditLogEntry.resource_id == resource)
    if start:
        statement = statement.where(AuditLogEntry.occurred_at >= start)
    if end:
        statement = statement.where(AuditLogEntry.occurred_at <= end)
    if department:
        statement = statement.where(AuditLogEntry.department == department)
    statement = statement.order_by(AuditLogEntry.occurred_at.desc(), AuditLogEntry.id.desc()).offset(offset).limit(limit)
    return list(session.exec(statement).all())
