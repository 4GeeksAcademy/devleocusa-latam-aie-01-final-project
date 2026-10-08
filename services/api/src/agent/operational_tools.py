from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel

from src.models.incident import IncidentBranch, IncidentCategory, IncidentOrigin, IncidentStatus

class ToolStatus(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class IncidentRecord(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: datetime
    updated_at: datetime | None = None


class IncidentLookupResult(BaseModel):
    status: ToolStatus
    incidents: list[IncidentRecord]
    message: str | None = None


class InventoryRecord(BaseModel):
    id: str
    name: str
    sku_code: str
    warehouse: str
    current_stock: int


class InventoryLookupResult(BaseModel):
    status: ToolStatus
    products: list[InventoryRecord]
    message: str | None = None