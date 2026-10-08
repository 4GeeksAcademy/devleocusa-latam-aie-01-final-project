from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator

from src.models.incident import IncidentBranch, IncidentCategory, IncidentOrigin, IncidentStatus


AgentSource = Literal["rag", "incidents", "inventory"]


class IncidentLookupInput(BaseModel):
    ticket_id: str | None = Field(default=None, min_length=1, max_length=100)
    status: IncidentStatus | None = None
    origin: IncidentOrigin | None = None
    branch: IncidentBranch | None = None
    category: IncidentCategory | None = None

    @model_validator(mode="after")
    def validate_search_criteria(self) -> "IncidentLookupInput":
        if not self.ticket_id and not any(
            (self.status, self.origin, self.branch, self.category)
        ):
            raise ValueError("ticket_id o al menos un filtro es obligatorio")
        return self


class InventoryLookupInput(BaseModel):
    product_query: str = Field(min_length=1, max_length=200)


class RoutingDecision(BaseModel):
    sources: list[AgentSource] = Field(min_length=1)
    incident: IncidentLookupInput | None = None
    inventory: InventoryLookupInput | None = None

    @model_validator(mode="after")
    def validate_tool_inputs(self) -> "RoutingDecision":
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources no puede contener valores duplicados")
        if "incidents" in self.sources and self.incident is None:
            raise ValueError("incident es obligatorio al consultar incidentes")
        if "inventory" in self.sources and self.inventory is None:
            raise ValueError("inventory es obligatorio al consultar inventario")
        return self


class AgentState(TypedDict, total=False):
    question: str
    context: list[dict[str, Any]]
    sources: list[AgentSource]
    completed_sources: list[AgentSource]
    incident_query: dict[str, Any]
    inventory_query: str
    incident_result: dict[str, Any]
    inventory_result: dict[str, Any]
    route_error: str
    answer: str
    error: str