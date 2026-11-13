"""Public lead intake and authenticated internal CRM endpoints."""

from __future__ import annotations

from uuid import UUID

from fastapi import APIRouter, Depends, HTTPException, Query, status

from src.models.lead import LeadCreate, LeadResponse, LeadStatus, LeadStatusUpdate, LeadUpdate
from src.models.user import Department, User, UserRole
from src.services.access_control import require_access
from src.services.leads_service import create_lead, delete_lead, get_lead, list_leads, update_lead, update_lead_status

leads_router = APIRouter(prefix="/leads", tags=["leads"])
_commercial_employee = require_access(UserRole.USER, Department.COMMERCIAL)
_commercial_supervisor = require_access(UserRole.MANAGER, Department.COMMERCIAL)


@leads_router.post("", response_model=LeadResponse, status_code=status.HTTP_201_CREATED)
def submit_lead(payload: LeadCreate) -> LeadResponse:
    """Accept a public contact form submission; status and ID are server-assigned."""
    return create_lead(payload)


@leads_router.get("", response_model=list[LeadResponse])
def get_leads(
    lead_status: LeadStatus | None = Query(default=None, alias="status"),
    _user: User = Depends(_commercial_employee),
) -> list[LeadResponse]:
    return list_leads(lead_status)


@leads_router.get("/{lead_id}", response_model=LeadResponse)
def get_lead_detail(lead_id: UUID, _user: User = Depends(_commercial_employee)) -> LeadResponse:
    lead = get_lead(lead_id)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado.")
    return lead


@leads_router.put("/{lead_id}", response_model=LeadResponse)
def put_lead(
    lead_id: UUID,
    payload: LeadUpdate,
    _user: User = Depends(_commercial_supervisor),
) -> LeadResponse:
    lead = update_lead(lead_id, payload)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado.")
    return lead


@leads_router.patch("/{lead_id}/status", response_model=LeadResponse)
def patch_lead_status(
    lead_id: UUID,
    payload: LeadStatusUpdate,
    _user: User = Depends(_commercial_supervisor),
) -> LeadResponse:
    lead = update_lead_status(lead_id, payload.status)
    if lead is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado.")
    return lead


@leads_router.delete("/{lead_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_lead(lead_id: UUID, _user: User = Depends(_commercial_supervisor)) -> None:
    if not delete_lead(lead_id):
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Lead no encontrado.")