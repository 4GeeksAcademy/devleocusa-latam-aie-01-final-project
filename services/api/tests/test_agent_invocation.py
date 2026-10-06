from __future__ import annotations

import asyncio
import json

from src.agent.graph import build_agent_graph
from src.agent.invocation import invoke_agent
from src.agent.operational_tools import IncidentLookupResult, IncidentRecord, ToolStatus
from src.agent.state import RoutingDecision


def test_invocation_persists_ordered_node_outputs(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "agent-traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_PATH", str(trace_path))
    context = [{"text": "Ventana estándar: 30 días.", "source_document": "returns.md"}]
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(sources=["rag"]),
        retrieve_fn=lambda _question: context,
        generate_fn=lambda _question, chunks: chunks[0]["text"],
    )

    result = asyncio.run(
        invoke_agent(
            graph,
            "¿Cuál es la ventana?",
            "test-run-1",
        )
    )

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    node_names = [event["node"] for event in trace["events"]]
    assert result["answer"] == "Ventana estándar: 30 días."
    assert node_names == ["validate_question", "classify", "retrieve", "generate_answer"]
    assert trace["run_id"] == "test-run-1"
    assert trace["events"][2]["output"] == {"context_items": 1}
    assert trace["events"][1]["output"] == {"sources": ["rag"], "route_failed": False}
    assert trace["answer"] == result["answer"]


def test_trace_records_tool_route_without_credentials_or_ticket_payload(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "private-trace.jsonl"
    monkeypatch.setenv("AGENT_TRACE_PATH", str(trace_path))
    graph = build_agent_graph(
        classify_fn=lambda _question: RoutingDecision(
            sources=["incidents"], incident={"ticket_id": "ticket-42"}
        ),
        incident_lookup_fn=lambda _query: IncidentLookupResult(
            status=ToolStatus.SUCCESS,
            incidents=[
                IncidentRecord.model_validate(
                    {
                        "id": "ticket-42",
                        "title": "private title",
                        "category": "Ultima_Milla",
                        "status": "open",
                        "origin": "customer",
                        "branch": "Zaragoza",
                        "created_at": "2026-10-01T12:00:00Z",
                    }
                )
            ],
        ),
        generate_fn=lambda _question, _evidence: "Ticket abierto.",
    )

    asyncio.run(
        invoke_agent(
            graph,
            "¿Estado del ticket ticket-42?",
            "private-run",
        )
    )

    trace_text = trace_path.read_text(encoding="utf-8")
    trace = json.loads(trace_text)
    assert [event["node"] for event in trace["events"]] == [
        "validate_question",
        "classify",
        "incident_tool",
        "generate_answer",
    ]
    assert trace["events"][2]["output"] == {"status": "success", "record_count": 1}
    assert "private title" not in trace_text