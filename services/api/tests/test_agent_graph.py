from __future__ import annotations

from langgraph.checkpoint.memory import InMemorySaver

from src.agent.graph import build_agent_graph


def test_empty_question_routes_to_error_without_retrieval() -> None:
    calls: list[str] = []
    graph = build_agent_graph(
        retrieve_fn=lambda question: calls.append(question) or [],
        generate_fn=lambda question, context: "should not run",
        no_context_message_fn=lambda: "sin contexto",
    )

    result = graph.invoke({"question": "   "})

    assert result["error"] == "La pregunta no puede estar vacía."
    assert result["answer"] == result["error"]
    assert calls == []


def test_empty_retrieval_routes_to_abstention_without_generation() -> None:
    calls: list[tuple[str, object]] = []
    graph = build_agent_graph(
        retrieve_fn=lambda question: calls.append(("retrieve", question)) or [],
        generate_fn=lambda question, context: calls.append(("generate", context)) or "respuesta",
        no_context_message_fn=lambda: "No tengo información relevante.",
    )

    result = graph.invoke({"question": "¿Cuál es la política?"})

    assert result["answer"] == "No tengo información relevante."
    assert calls == [("retrieve", "¿Cuál es la política?")]


def test_generation_receives_the_context_retrieved_by_the_graph() -> None:
    context = [{"text": "Ventana estándar: 30 días.", "_score": 0.92}]
    received: list[tuple[str, list[dict]]] = []
    graph = build_agent_graph(
        retrieve_fn=lambda _question: context,
        generate_fn=lambda question, chunks: received.append((question, chunks)) or "30 días",
        no_context_message_fn=lambda: "sin contexto",
    )

    result = graph.invoke({"question": "¿Cuántos días tengo?"})

    assert result["answer"] == "30 días"
    assert received == [("¿Cuántos días tengo?", context)]


def test_checkpointer_keeps_each_node_transition() -> None:
    context = [{"text": "30 días"}]
    graph = build_agent_graph(
        checkpointer=InMemorySaver(),
        retrieve_fn=lambda _question: context,
        generate_fn=lambda _question, _context: "30 días",
    )
    config = {"configurable": {"thread_id": "checkpoint-test"}}

    graph.invoke({"question": "¿Cuál es la ventana?"}, config=config)
    history = list(graph.get_state_history(config))

    assert len(history) >= 4
    assert history[0].values["answer"] == "30 días"
    assert any(snapshot.values.get("context") == context for snapshot in history)