from __future__ import annotations

from collections.abc import Awaitable, Callable
import inspect
import json
from typing import Any

from src.agent import rag_adapter
from src.agent import routing as routing_adapter
from src.agent.operational_tools import IncidentLookupResult, InventoryLookupResult
from src.agent.state import (
    AgentState,
    IncidentLookupInput,
    InventoryLookupInput,
    MemoryGeneration,
    RoutingDecision,
)
from src.agent.memory_generation import generate_answer_and_proposal

RetrieveFn = Callable[[str], list[dict[str, Any]]]
GenerateAnswerFn = Callable[[str, list[dict[str, Any]]], str]
NoContextMessageFn = Callable[[], str]
ClassifyFn = Callable[[str], RoutingDecision]
IncidentLookupFn = Callable[
    [IncidentLookupInput], IncidentLookupResult | Awaitable[IncidentLookupResult]
]
InventoryLookupFn = Callable[
    [InventoryLookupInput], InventoryLookupResult | Awaitable[InventoryLookupResult]
]

INCIDENT_FALLBACK = "No puedo confirmar el estado de ese ticket ahora mismo."
INVENTORY_FALLBACK = "No puedo confirmar el stock de ese producto ahora mismo."


def validate_question(state: AgentState) -> dict[str, str]:
    question = state.get("question")
    if not isinstance(question, str) or not question.strip():
        return {
            "error": "La pregunta no puede estar vacía.",
            "answer": "La pregunta no puede estar vacía.",
        }
    return {"question": question.strip(), "error": ""}


def retrieve_context(
    state: AgentState,
    *,
    retrieve_fn: RetrieveFn | None = None,
) -> dict[str, list[dict[str, Any]]]:
    retrieve_fn = retrieve_fn or rag_adapter.retrieve
    return {
        "context": retrieve_fn(state["question"]),
        "completed_sources": [*state.get("completed_sources", []), "rag"],
    }


def classify_question(
    state: AgentState,
    *,
    classify_fn: ClassifyFn | None = None,
) -> dict[str, Any]:
    classify_fn = classify_fn or routing_adapter.classify_question
    try:
        decision = classify_fn(state["question"])
    except Exception:
        return {
            "sources": [],
            "completed_sources": [],
            "route_error": "No se pudo determinar qué fuentes consultar.",
        }

    return {
        "sources": decision.sources,
        "completed_sources": [],
        "incident_query": decision.incident.model_dump(mode="json") if decision.incident else {},
        "inventory_query": decision.inventory.product_query if decision.inventory else "",
        "route_error": "",
    }


async def lookup_incidents(
    state: AgentState,
    *,
    lookup_fn: IncidentLookupFn | None = None,
) -> dict[str, Any]:
    try:
        if lookup_fn is None:
            raise RuntimeError("MCP incident tools are not configured.")
        query = IncidentLookupInput.model_validate(state.get("incident_query", {}))
        result = lookup_fn(query)
        if inspect.isawaitable(result):
            result = await result
        result = result.model_dump(mode="json")
    except Exception:
        result = {"status": "unavailable", "incidents": [], "message": "service_error"}
    return {
        "incident_result": result,
        "completed_sources": [*state.get("completed_sources", []), "incidents"],
    }


async def lookup_inventory(
    state: AgentState,
    *,
    lookup_fn: InventoryLookupFn | None = None,
) -> dict[str, Any]:
    try:
        if lookup_fn is None:
            raise RuntimeError("MCP inventory tools are not configured.")
        query = InventoryLookupInput(product_query=state.get("inventory_query", ""))
        result = lookup_fn(query)
        if inspect.isawaitable(result):
            result = await result
        result = result.model_dump(mode="json")
    except Exception:
        result = {"status": "unavailable", "products": [], "message": "service_error"}
    return {
        "inventory_result": result,
        "completed_sources": [*state.get("completed_sources", []), "inventory"],
    }


def generate_response(
    state: AgentState,
    *,
    generate_fn: GenerateAnswerFn | None = None,
) -> dict[str, Any]:
    evidence = list(state.get("context", []))
    incident_result = state.get("incident_result")
    inventory_result = state.get("inventory_result")

    if incident_result and incident_result.get("status") == "success":
        evidence.append({"source": "incidents", "text": json.dumps(incident_result["incidents"], ensure_ascii=False)})
    if inventory_result and inventory_result.get("status") == "success":
        evidence.append({"source": "inventory", "text": json.dumps(inventory_result["products"], ensure_ascii=False)})

    if incident_result and incident_result.get("status") == "not_found":
        return {"answer": "No encontré un ticket que coincida; no puedo confirmar su estado."}
    if incident_result and incident_result.get("status") == "unavailable":
        return {"answer": INCIDENT_FALLBACK}
    if inventory_result and inventory_result.get("status") == "not_found":
        return {"answer": "No encontré ese producto; no puedo confirmar su stock."}
    if inventory_result and inventory_result.get("status") == "unavailable":
        return {"answer": INVENTORY_FALLBACK}

    if not evidence:
        return respond_without_context(state)

    if generate_fn is not None:
        return {"answer": generate_fn(state["question"], evidence), "memory_proposal": None}
    try:
        result = generate_answer_and_proposal(
            state["question"], evidence, state.get("memories", [])
        )
    except Exception:
        # Preserve response availability if structured self-evaluation fails.
        return {"answer": rag_adapter.generate_answer(state["question"], evidence), "memory_proposal": None}
    answer = result.answer
    proposal = result.proposal
    if proposal:
        answer = f"{answer}\n\n¿Quieres que recuerde esto para la próxima vez: “{proposal.content}”?"
    return {
        "answer": answer,
        "memory_proposal": proposal.model_dump() if proposal else None,
    }


def respond_without_context(
    _state: AgentState,
    *,
    message_fn: NoContextMessageFn | None = None,
) -> dict[str, str]:
    message_fn = message_fn or rag_adapter.no_context_message
    return {"answer": message_fn()}


def route_after_validation(state: AgentState) -> str:
    return "invalid_question" if state.get("error") else "classify"


def route_after_classification(state: AgentState) -> str:
    if state.get("route_error"):
        return "route_failure"
    return _next_source(state)


def route_after_source(state: AgentState) -> str:
    next_node = _next_source(state)
    if (
        next_node == "generate_answer"
        and state.get("sources") == ["rag"]
        and not state.get("context")
    ):
        return "no_context"
    return next_node


def _next_source(state: AgentState) -> str:
    completed = set(state.get("completed_sources", []))
    selected = set(state.get("sources", []))
    for source, node in (("rag", "retrieve"), ("incidents", "incident_tool"), ("inventory", "inventory_tool")):
        if source in selected and source not in completed:
            return node
    return "generate_answer"


def respond_to_route_failure(_state: AgentState) -> dict[str, str]:
    return {"answer": "No pude determinar qué información consultar. Inténtalo de nuevo."}