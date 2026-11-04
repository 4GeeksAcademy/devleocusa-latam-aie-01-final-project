"""Development bootstrap: demo tenant assignment and seed data.

These helpers keep the local backoffice usable out of the box:

  * assign a default tenant to operator accounts that have none, so the
    tenant-scoped incidents API does not fail closed with HTTP 403;
  * seed the TinyDB suppliers directory when it is empty;
  * seed a handful of demo CRM leads when the prospect list is empty.

Everything here is a **no-op in production** (``TRACKFLOW_ENV=production``)
and can be disabled with ``ENABLE_DEMO_BOOTSTRAP=false``. Authorization
checks remain unchanged: unassigned identities still fail closed at request
time unless the development bootstrap has provisioned them.
"""

from __future__ import annotations

import os

from src.database import get_leads_table, get_suppliers_table, get_users_table
from src.models.user import UserRole
from src.seed import build_seed_leads, build_seed_suppliers

DEFAULT_TENANT_ID = os.getenv("DEFAULT_TENANT_ID", "trackflow-demo").strip() or "trackflow-demo"

_OPERATOR_ROLES = {
    UserRole.ADMIN.value,
    UserRole.MANAGER.value,
    UserRole.SERVICE.value,
}


def _demo_bootstrap_enabled() -> bool:
    """Return True only for non-production environments without an explicit opt-out."""
    if os.getenv("TRACKFLOW_ENV", "development").strip().lower() == "production":
        return False

    raw_value = os.getenv("ENABLE_DEMO_BOOTSTRAP", "true").strip().lower()
    return raw_value not in {"0", "false", "no", "off"}


def ensure_operator_tenants(tenant_id: str | None = None) -> int:
    """Assign ``tenant_id`` to operator accounts that have none.

    Returns the number of users updated. Users that already have a tenant are
    left untouched, which keeps the operation idempotent.
    """
    resolved_tenant = (tenant_id or DEFAULT_TENANT_ID).strip() or DEFAULT_TENANT_ID
    users_table = get_users_table()

    updated = 0
    for document in users_table.all():
        if document.get("tenant_id"):
            continue
        if document.get("role") not in _OPERATOR_ROLES:
            continue

        users_table.update({"tenant_id": resolved_tenant}, doc_ids=[document.doc_id])
        updated += 1

    return updated


def ensure_suppliers_seeded() -> int:
    """Seed the suppliers directory when the TinyDB table is empty."""
    suppliers_table = get_suppliers_table()
    if len(suppliers_table) > 0:
        return 0

    payload = [supplier.model_dump(mode="json") for supplier in build_seed_suppliers()]
    return len(suppliers_table.insert_multiple(payload))


def ensure_leads_seeded() -> int:
    """Seed demo CRM leads when the TinyDB table is empty.

    The backoffice prospect list ("Gestión de prospectos") is empty on a
    fresh local database. A handful of demo leads with varied statuses keeps
    the panel meaningful for demonstrations. Existing leads are never
    overwritten or duplicated.
    """
    leads_table = get_leads_table()
    if len(leads_table) > 0:
        return 0

    payload = [lead.model_dump(mode="json") for lead in build_seed_leads()]
    return len(leads_table.insert_multiple(payload))


def ensure_executive_kpis_seeded() -> bool:
    """Seed demo executive KPIs when the reporting store has no records.

    The executive dashboard reads ``operational_cost`` and
    ``customer_satisfaction`` from the KPI records produced by the data
    pipeline. Without a pipeline run those cards render "N/D", so a demo
    record keeps the panel meaningful locally. Existing records are never
    overwritten.
    """
    from reporting.seed import seed_demo_kpis

    return seed_demo_kpis()


def run_demo_bootstrap() -> None:
    """Run every development bootstrap step. Safe to call on each startup."""
    if not _demo_bootstrap_enabled():
        return

    tenants = ensure_operator_tenants()
    suppliers = ensure_suppliers_seeded()
    leads = ensure_leads_seeded()
    kpis_written = ensure_executive_kpis_seeded()

    if tenants or suppliers or leads or kpis_written:
        print(
            "[bootstrap] demo data applied: "
            f"{tenants} operator(s) assigned to tenant '{DEFAULT_TENANT_ID}', "
            f"{suppliers} supplier(s) inserted, "
            f"{leads} demo lead(s) inserted, "
            f"executive KPIs seeded: {kpis_written}."
        )
