from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace

from langgraph.checkpoint.memory import InMemorySaver

from src.agent import routing
from src.agent.graph import build_agent_graph
from src.agent.operational_tools import (
    IncidentLookupResult,
    IncidentRecord,
    InventoryLookupResult,
    InventoryRecord,
    ToolStatus,
)
from src.agent.state import RoutingDecision


def _rag_route(_question: str) -> RoutingDecision:
    return RoutingDecision(sources=["rag"])


def test_llm_classifier_parses_a_typed_tool_decision(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeOpenAI:
        def __init__(self, *, api_key: str | None, base_url: str, timeout: float) -> None:
            captured["api_key"] = api_key
            captured["base_url"] = base_url
            captured["timeout"] = timeout
            self.chat = SimpleNamespace(completions=SimpleNamespace(create=self.create))

        @staticmethod
        def create(**kwargs):
            captured.update(kwargs)
            response_json = json.dumps(
                {
                    "sources": ["incidents"],
                    "incident": {
                        "ticket_id": "ticket-42",
                        "status": None,
                        "origin": None,
                        "branch": None,
                        "category": None,
                    },
                    "inventory": None,
                }
            )
            message = SimpleNamespace(content=response_json)
            return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    monkeypatch.setattr(routing, "OpenAI", FakeOpenAI)
    monkeypatch.setenv("AGENT_ROUTER_MODEL", "router-test-model")

    decision = routing.classify_question("¿En qué estado está el ticket ticket-42?")

    assert decision.sources == ["incidents"]
    assert decision.incident.ticket_id == "ticket-42"
    assert captured["timeout"] == 10.0
    assert captured["base_url"] == "https://api.openai.com/v1"
    assert captured["model"] == "router-test-model"
    assert captured["response_format"] == {"type": "json_object"}


def test_empty_question_routes_to_error_without_retrieval() -> None:
    calls: list[str] = []
    graph = build_agent_graph(
        classify_fn=_rag_route,
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
        classify_fn=_rag_route,
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
        classify_fn=_rag_route,
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
        classify_fn=_rag_route,
        retrieve_fn=lambda _question: context,
        generate_fn=lambda _question, _context: "30 días",
    )
    config = {"configurable": {"thread_id": "checkpoint-test"}}

    graph.invoke({"question": "¿Cuál es la ventana?"}, config=config)
    history = list(graph.get_state_history(config))

    assert len(history) >= 4
    assert history[0].values["answer"] == "30 días"
    assert any(snapshot.values.get("context") == context for snapshot in history)


def test_incident_route_skips_rag_and_generates_from_tool_result() -> None:
    calls: list[str] = []
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["incidents"], incident={"ticket_id": "ticket-42"}
        ),
        retrieve_fn=lambda _question: calls.append("rag") or [],
            incident_lookup_fn=lambda query: calls.append(query.ticket_id)
            or IncidentLookupResult(
                status=ToolStatus.SUCCESS,
                incidents=[
                    IncidentRecord.model_validate(
                        {
                            "id": "ticket-42",
                            "title": "Retraso",
                            "category": "Ultima_Milla",
                            "status": "open",
                            "origin": "customer",
                            "branch": "Zaragoza",
                            "created_at": "2026-10-01T12:00:00Z",
                        }
                    )
                ],
            ),
        generate_fn=lambda _question, evidence: evidence[0]["text"],
    )

    result = asyncio.run(graph.ainvoke({"question": "¿En qué estado está el ticket ticket-42?"}))

    assert '"status": "open"' in result["answer"]
    assert calls == ["ticket-42"]


def test_operational_failure_returns_honest_fallback() -> None:
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["incidents"], incident={"ticket_id": "ticket-42"}
        ),
            incident_lookup_fn=lambda _query: IncidentLookupResult(
                status=ToolStatus.UNAVAILABLE,
                incidents=[],
                message="timeout",
            ),
    )

    result = asyncio.run(graph.ainvoke({"question": "¿En qué estado está el ticket ticket-42?"}))

    assert result["answer"] == "No puedo confirmar el estado de ese ticket ahora mismo."


def test_mixed_question_uses_rag_then_incident_tool() -> None:
    calls: list[str] = []
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["rag", "incidents"], incident={"ticket_id": "ticket-42"}
        ),
        retrieve_fn=lambda _question: calls.append("rag")
        or [{"source": "rag", "text": "SLA: 48 horas"}],
        incident_lookup_fn=lambda _query: calls.append("incidents")
            or IncidentLookupResult(
                status=ToolStatus.SUCCESS,
                incidents=[
                    IncidentRecord.model_validate(
                        {
                            "id": "ticket-42",
                            "title": "Retraso",
                            "category": "Ultima_Milla",
                            "status": "open",
                            "origin": "customer",
                            "branch": "Zaragoza",
                            "created_at": "2026-10-01T12:00:00Z",
                        }
                    )
                ],
            ),
        generate_fn=lambda _question, evidence: " | ".join(row["source"] for row in evidence),
    )

    result = asyncio.run(graph.ainvoke({"question": "¿Estado del ticket y cuál es el SLA?"}))

    assert result["answer"] == "rag | incidents"
    assert calls == ["rag", "incidents"]


def test_inventory_route_skips_rag() -> None:
    calls: list[str] = []
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["inventory"], inventory={"product_query": "CBL-001"}
        ),
        retrieve_fn=lambda _question: calls.append("rag") or [],
            inventory_lookup_fn=lambda query: calls.append(query.product_query)
            or InventoryLookupResult(
                status=ToolStatus.SUCCESS,
                products=[
                    InventoryRecord(
                        id="sku-1",
                        name="Cable USB",
                        sku_code=query.product_query,
                        warehouse="Zaragoza",
                        current_stock=12,
                    )
                ],
            ),
        generate_fn=lambda _question, evidence: evidence[0]["text"],
    )

    result = asyncio.run(graph.ainvoke({"question": "¿Hay stock del SKU CBL-001?"}))

    assert '"current_stock": 12' in result["answer"]
    assert calls == ["CBL-001"]


def test_inventory_failure_returns_honest_fallback() -> None:
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["inventory"], inventory={"product_query": "CBL-001"}
        ),
        inventory_lookup_fn=lambda _query: {
            "status": "unavailable",
            "products": [],
            "message": "timeout",
        },
    )

    result = asyncio.run(graph.ainvoke({"question": "¿Hay stock del SKU CBL-001?"}))

    assert result["answer"] == "No puedo confirmar el stock de ese producto ahora mismo."