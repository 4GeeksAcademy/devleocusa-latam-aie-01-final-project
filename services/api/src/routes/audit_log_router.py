"""Protected audit-log query and integrity endpoints."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlmodel import Session

from src.database import get_sql_session
from src.models.audit_log import AuditLogEntry
from src.models.user import User, UserRole
from src.services.audit_log_service import list_events, verify_chain
from src.services.auth_service import get_current_user

audit_log_router = APIRouter(prefix="/audit-log", tags=["audit-log"])


def _authorized_viewer(current_user: User = Depends(get_current_user)) -> User:
    if current_user.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Sin acceso al registro de auditoría.")
    if current_user.role == UserRole.MANAGER and current_user.department is None:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="El supervisor no tiene departamento asignado.")
    return current_user


def _serialize(entry: AuditLogEntry) -> dict[str, Any]:
    return {
        "id": entry.id,
        "actor_id": entry.actor_id,
        "actor_type": entry.actor_type,
        "actor_name": entry.actor_name,
        "action": entry.action,
        "resource_type": entry.resource_type,
        "resource_id": entry.resource_id,
        "occurred_at": entry.occurred_at.isoformat(),
        "source": entry.source,
        "department": entry.department,
        "country": entry.country,
        "warehouse_id": entry.warehouse_id,
        "details": json.loads(entry.details_json),
        "previous_hash": entry.previous_hash,
        "event_hash": entry.event_hash,
    }


@audit_log_router.get("")
def get_audit_events(
    actor: str | None = None,
    action: str | None = None,
    resource: str | None = None,
    start: datetime | None = None,
    end: datetime | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    session: Session = Depends(get_sql_session),
    current_user: User = Depends(_authorized_viewer),
) -> dict[str, Any]:
    if start and end and start > end:
        raise HTTPException(status_code=422, detail="El inicio no puede ser posterior al final.")
    department = current_user.department.value if current_user.role == UserRole.MANAGER and current_user.department else None
    events = list_events(
        session,
        actor=actor,
        action=action,
        resource=resource,
        start=start,
        end=end,
        department=department,
        limit=limit,
        offset=offset,
    )
    return {"items": [_serialize(item) for item in events], "limit": limit, "offset": offset}


@audit_log_router.get("/integrity")
def get_audit_integrity(
    session: Session = Depends(get_sql_session),
    current_user: User = Depends(_authorized_viewer),
) -> dict[str, Any]:
    # A single global chain cannot be verified from only a supervisor's
    # department slice. Per policy, only Admin receives global chain status.
    if current_user.role != UserRole.ADMIN:
        raise HTTPException(status_code=403, detail="Solo Admin puede verificar la cadena global.")
    return verify_chain(session)
