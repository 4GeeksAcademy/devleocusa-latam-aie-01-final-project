"""TinyDB persistence operations for the lead intake and CRM."""

from __future__ import annotations

from datetime import timezone
from uuid import UUID, uuid4

from tinydb import Query
from tinydb.table import Document

from src.database import get_leads_table
from src.models.lead import LeadCreate, LeadResponse, LeadStatus, LeadUpdate, utc_now


def _serialize(document: Document | dict) -> LeadResponse:
    data = dict(document)
    data["id"] = str(data["id"])
    return LeadResponse.model_validate(data)


def create_lead(payload: LeadCreate) -> LeadResponse:
    now = utc_now()
    data = payload.model_dump(mode="json", by_alias=True)
    data.update({"id": str(uuid4()), "status": LeadStatus.NEW.value, "created_at": now.isoformat(), "updated_at": now.isoformat()})
    table = get_leads_table()
    doc_id = table.insert(data)
    document = table.get(doc_id=doc_id)
    if document is None:
        raise RuntimeError("No se pudo guardar la solicitud de contacto")
    return _serialize(document)


def list_leads(status: LeadStatus | None = None) -> list[LeadResponse]:
    table = get_leads_table()
    documents = table.all() if status is None else table.search(Query().status == status.value)
    documents.sort(key=lambda item: str(item.get("created_at", "")), reverse=True)
    return [_serialize(document) for document in documents]


def get_lead(lead_id: UUID) -> LeadResponse | None:
    document = get_leads_table().get(Query().id == str(lead_id))
    return _serialize(document) if document is not None else None


def update_lead(lead_id: UUID, payload: LeadUpdate) -> LeadResponse | None:
    table = get_leads_table()
    document = table.get(Query().id == str(lead_id))
    if document is None:
        return None
    values = payload.model_dump(mode="json", by_alias=True)
    values["updated_at"] = utc_now().isoformat()
    table.update(values, doc_ids=[document.doc_id])
    return get_lead(lead_id)


def update_lead_status(lead_id: UUID, status: LeadStatus) -> LeadResponse | None:
    table = get_leads_table()
    document = table.get(Query().id == str(lead_id))
    if document is None:
        return None
    table.update({"status": status.value, "updated_at": utc_now().isoformat()}, doc_ids=[document.doc_id])
    return get_lead(lead_id)


def delete_lead(lead_id: UUID) -> bool:
    return bool(get_leads_table().remove(Query().id == str(lead_id)))