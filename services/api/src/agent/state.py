from __future__ import annotations

from typing import Any, Literal, TypedDict

from pydantic import BaseModel, Field, model_validator
from src.agent.memory_models import MemoryProposal

from src.models.incident import IncidentBranch, IncidentCategory, IncidentOrigin, IncidentStatus


AgentSource = Literal["rag", "incidents", "inventory"]
AgentScope = Literal[
    "trackflow",
    "casual",
    "personal",
    "out_of_scope",
    "instruction_override",
]


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
    scope: AgentScope = "trackflow"
    sources: list[AgentSource] = Field(default_factory=list)
    incident: IncidentLookupInput | None = None
    inventory: InventoryLookupInput | None = None

    @model_validator(mode="after")
    def validate_tool_inputs(self) -> "RoutingDecision":
        if self.scope == "trackflow" and not self.sources:
            raise ValueError("Una consulta TrackFlow debe seleccionar al menos una fuente")
        if self.scope != "trackflow" and self.sources:
            raise ValueError("Una consulta fuera de dominio no puede seleccionar fuentes")
        if len(set(self.sources)) != len(self.sources):
            raise ValueError("sources no puede contener valores duplicados")
        if "incidents" in self.sources and self.incident is None:
            raise ValueError("incident es obligatorio al consultar incidentes")
        if "inventory" in self.sources and self.inventory is None:
            raise ValueError("inventory es obligatorio al consultar inventario")
        return self


class MemoryGeneration(BaseModel):
    answer: str
    proposal: MemoryProposal | None = None


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
    memories: list[str]
    memory_proposal: dict[str, str] | None
    user_id: str
    pending_proposal: dict[str, Any] | None
    guardrail_action: str
    guardrail_category: str
    guardrail_reason: str
    guardrail_event: dict[str, str]
    routing_decision: dict[str, Any]