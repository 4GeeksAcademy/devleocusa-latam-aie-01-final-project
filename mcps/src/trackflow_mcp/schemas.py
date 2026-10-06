from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class IncidentCategory(str, Enum):
    ALMACEN = "Almacen"
    ULTIMA_MILLA = "Ultima_Milla"
    LOGISTICA_INVERSA = "Logistica_Inversa"
    CX = "CX"
    COMERCIAL = "Comercial"
    TECNOLOGIA = "Tecnologia"


class IncidentStatus(str, Enum):
    OPEN = "open"
    IN_PROGRESS = "in_progress"
    RESOLVED = "resolved"
    DISCARDED = "discarded"


class IncidentOrigin(str, Enum):
    CUSTOMER = "customer"
    BRANCH = "branch"
    INTERNAL = "internal"


class IncidentBranch(str, Enum):
    LOS_ANGELES = "Los Ángeles"
    ZARAGOZA = "Zaragoza"
    CENTRAL = "Central"


class IncidentRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Company incident ID returned by Incidents Manager.")
    title: str
    description: str | None = None
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: datetime
    updated_at: datetime | None = None


class IncidentStatusResult(BaseModel):
    id: str
    status: IncidentStatus
    updated_at: datetime


class IncidentListResult(BaseModel):
    incidents: list[IncidentRecord]


class InventoryRecord(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str = Field(description="Company SKU ID.")
    name: str
    sku_code: str
    warehouse: str
    current_stock: int = Field(
        description="Live stock balance calculated by the TrackFlow inventory API."
    )


class InventorySearchResult(BaseModel):
    products: list[InventoryRecord]


class IncidentListQuery(BaseModel):
    status: IncidentStatus | None = None
    origin: IncidentOrigin | None = None
    branch: IncidentBranch | None = None
    category: IncidentCategory | None = None

    @model_validator(mode="after")
    def require_filter(self) -> "IncidentListQuery":
        if not any(value is not None for value in self.model_dump().values()):
            raise ValueError("At least one incident filter is required.")
        return self