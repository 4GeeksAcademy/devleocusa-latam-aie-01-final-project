"""Idempotent development-only audit examples for the backoffice viewer."""

from __future__ import annotations

from sqlmodel import Session, select

from src.database import get_engine
from src.models.audit_log import AuditLogEntry
from src.services.audit_log_service import append_event


def ensure_audit_examples() -> int:
    """Insert fifteen synthetic examples once; callers must disable this in prod."""
    with Session(get_engine()) as session:
        existing = session.exec(
            select(AuditLogEntry.id).where(AuditLogEntry.actor_id == "audit-seed")
        ).first()
        if existing:
            return 0

        actions = [
            ("inventory.adjusted", "inventory", "Operaciones de Almacén"),
            ("return.approved", "return", "Logística Inversa (Devoluciones)"),
            ("return.rejected", "return", "Logística Inversa (Devoluciones)"),
            ("carrier.assignment.changed", "shipment", "Última Milla y Gestión de Carriers"),
            ("user.updated", "user", "Personas"),
        ]
        warehouses = [("Estados Unidos", "warehouse-los-angeles"), ("España", "warehouse-zaragoza")]
        for index in range(15):
            action, resource_type, department = actions[index % len(actions)]
            country, warehouse_id = warehouses[index % len(warehouses)]
            is_warehouse = action == "inventory.adjusted"
            append_event(
                session,
                actor_id="audit-seed",
                actor_type="process",
                actor_name="Datos de demostración",
                action=action,
                resource_type=resource_type,
                resource_id=f"demo-{resource_type}-{index + 1:02d}",
                source="demo-bootstrap",
                department=department,
                country=country if is_warehouse else None,
                warehouse_id=warehouse_id if is_warehouse else None,
                details={"demo": True, "description": "Evento sintético de ejemplo"},
            )
        session.commit()
        return 15