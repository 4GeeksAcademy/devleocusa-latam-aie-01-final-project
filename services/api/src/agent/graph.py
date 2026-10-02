from __future__ import annotations

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from src.agent.nodes import (
    GenerateAnswerFn,
    NoContextMessageFn,
    RetrieveFn,
    generate_response,
    respond_without_context,
    retrieve_context,
    route_after_retrieval,
    route_after_validation,
    validate_question,
)
from src.agent.state import AgentState


def build_agent_graph(
    *,
    checkpointer: BaseCheckpointSaver | None = None,
    retrieve_fn: RetrieveFn | None = None,
    generate_fn: GenerateAnswerFn | None = None,
    no_context_message_fn: NoContextMessageFn | None = None,
):
    builder = StateGraph(AgentState)
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

    builder.add_edge(START, "validate_question")
    builder.add_conditional_edges(
        "validate_question",
        route_after_validation,
        {"retrieve": "retrieve", "invalid_question": "invalid_question"},
    )
    builder.add_conditional_edges(
        "retrieve",
        route_after_retrieval,
        {"generate_answer": "generate_answer", "no_context": "no_context"},
    )
    builder.add_edge("invalid_question", END)
    builder.add_edge("generate_answer", END)
    builder.add_edge("no_context", END)

    return builder.compile(checkpointer=checkpointer)