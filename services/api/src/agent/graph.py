from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.runtime import Runtime

from src.agent.nodes import (
    ClassifyFn,
    GenerateAnswerFn,
    IncidentLookupFn,
    InventoryLookupFn,
    NoContextMessageFn,
    RetrieveFn,
    classify_question,
    generate_response,
    lookup_incidents,
    lookup_inventory,
    respond_to_route_failure,
    respond_without_context,
    retrieve_context,
    route_after_classification,
    route_after_source,
    route_after_validation,
    validate_question,
)
from src.agent.state import AgentContext, AgentState


def build_agent_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    retrieve_fn: RetrieveFn | None = None,
    generate_fn: GenerateAnswerFn | None = None,
    no_context_message_fn: NoContextMessageFn | None = None,
    classify_fn: ClassifyFn | None = None,
    incident_lookup_fn: IncidentLookupFn | None = None,
    inventory_lookup_fn: InventoryLookupFn | None = None,
):
    builder = StateGraph(AgentState, context_schema=AgentContext)
    builder.add_node("validate_question", validate_question)
    builder.add_node(
        "invalid_question",
        lambda state: {"error": state["error"], "answer": state["answer"]},
    )
    builder.add_node(
        "retrieve",
        lambda state: retrieve_context(state, retrieve_fn=retrieve_fn),
    )
    builder.add_node(
        "classify",
        lambda state: classify_question(state, classify_fn=classify_fn),
    )
    builder.add_node(
        "incident_tool",
        lambda state, runtime: lookup_incidents(
            state,
            lookup_fn=incident_lookup_fn,
            authorization=(runtime.context or {}).get("authorization", ""),
        ),
    )
    builder.add_node(
        "inventory_tool",
        lambda state, runtime: lookup_inventory(
            state,
            lookup_fn=inventory_lookup_fn,
            authorization=(runtime.context or {}).get("authorization", ""),
        ),
    )
    builder.add_node(
        "generate_answer",
        lambda state: generate_response(state, generate_fn=generate_fn),
    )
    builder.add_node(
        "no_context",
        lambda state: respond_without_context(
            state,
            message_fn=no_context_message_fn,
        ),
    )
    builder.add_node("route_failure", respond_to_route_failure)

    builder.add_edge(START, "validate_question")
    builder.add_conditional_edges(
        "validate_question",
        route_after_validation,
        {"classify": "classify", "invalid_question": "invalid_question"},
    )
    source_routes = {
        "retrieve": "retrieve",
        "incident_tool": "incident_tool",
        "inventory_tool": "inventory_tool",
        "generate_answer": "generate_answer",
        "no_context": "no_context",
    }
    builder.add_conditional_edges(
        "classify",
        route_after_classification,
        {**source_routes, "route_failure": "route_failure"},
    )
    for source_node in ("retrieve", "incident_tool", "inventory_tool"):
        builder.add_conditional_edges(source_node, route_after_source, source_routes)
    builder.add_edge("invalid_question", END)
    builder.add_edge("generate_answer", END)
    builder.add_edge("no_context", END)
    builder.add_edge("route_failure", END)

    return builder.compile(checkpointer=checkpointer)