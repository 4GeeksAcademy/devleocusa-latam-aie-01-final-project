from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from src.agent.nodes import (
    ClassifyFn,
    CasualAnswerFn,
    GenerateAnswerFn,
    IncidentLookupFn,
    InventoryLookupFn,
    NoContextMessageFn,
    RetrieveFn,
    classify_question,
    generate_response,
    guard_user_input,
    lookup_incidents,
    lookup_inventory,
    respond_to_route_failure,
    respond_without_context,
    retrieve_context,
    route_after_classification,
    route_after_source,
    route_after_input_guard,
    route_after_validation,
    validate_question,
    validate_response_output,
)
from src.agent.state import AgentState


def build_agent_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    retrieve_fn: RetrieveFn | None = None,
    generate_fn: GenerateAnswerFn | None = None,
    no_context_message_fn: NoContextMessageFn | None = None,
    classify_fn: ClassifyFn | None = None,
    incident_lookup_fn: IncidentLookupFn | None = None,
    inventory_lookup_fn: InventoryLookupFn | None = None,
    casual_fn: CasualAnswerFn | None = None,
):
    builder = StateGraph(AgentState)
    builder.add_node("validate_question", validate_question)
    builder.add_node(
        "guard_user_input",
        lambda state: guard_user_input(state, casual_fn=casual_fn),
    )
    builder.add_node("guardrail_response", lambda _state: {})
    builder.add_node("validate_response_output", validate_response_output)
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
        lambda state: classify_question(
            state, classify_fn=classify_fn, casual_fn=casual_fn
        ),
    )
    async def incident_tool_node(state: AgentState) -> dict:
        return await lookup_incidents(state, lookup_fn=incident_lookup_fn)

    async def inventory_tool_node(state: AgentState) -> dict:
        return await lookup_inventory(state, lookup_fn=inventory_lookup_fn)

    builder.add_node("incident_tool", incident_tool_node)
    builder.add_node("inventory_tool", inventory_tool_node)
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
        {"classify": "guard_user_input", "invalid_question": "invalid_question"},
    )
    builder.add_conditional_edges(
        "guard_user_input",
        route_after_input_guard,
        {"classify": "classify", "guardrail_response": "guardrail_response"},
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
        {
            **source_routes,
            "route_failure": "route_failure",
            "guardrail_response": "guardrail_response",
        },
    )
    for source_node in ("retrieve", "incident_tool", "inventory_tool"):
        builder.add_conditional_edges(source_node, route_after_source, source_routes)
    for final_node in (
        "invalid_question", "guardrail_response", "generate_answer", "no_context", "route_failure"
    ):
        builder.add_edge(final_node, "validate_response_output")
    builder.add_edge("validate_response_output", END)

    return builder.compile(checkpointer=checkpointer)