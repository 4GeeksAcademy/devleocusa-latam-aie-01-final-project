from __future__ import annotations

from collections.abc import Callable
from typing import Any

from src.agent import rag_adapter
from src.agent.state import AgentState

RetrieveFn = Callable[[str], list[dict[str, Any]]]
GenerateAnswerFn = Callable[[str, list[dict[str, Any]]], str]
NoContextMessageFn = Callable[[], str]


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
    return {"context": retrieve_fn(state["question"])}


def generate_response(
    state: AgentState,
    *,
    generate_fn: GenerateAnswerFn | None = None,
) -> dict[str, str]:
    generate_fn = generate_fn or rag_adapter.generate_answer
    return {"answer": generate_fn(state["question"], state["context"])}


def respond_without_context(
    _state: AgentState,
    *,
    message_fn: NoContextMessageFn | None = None,
) -> dict[str, str]:
    message_fn = message_fn or rag_adapter.no_context_message
    return {"answer": message_fn()}


def route_after_validation(state: AgentState) -> str:
    return "invalid_question" if state.get("error") else "retrieve"


def route_after_retrieval(state: AgentState) -> str:
    return "generate_answer" if state.get("context") else "no_context"