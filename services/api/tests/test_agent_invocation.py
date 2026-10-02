from __future__ import annotations

import asyncio
import json

from src.agent.graph import build_agent_graph
from src.agent.invocation import invoke_agent


def test_invocation_persists_ordered_node_outputs(monkeypatch, tmp_path) -> None:
    trace_path = tmp_path / "agent-traces.jsonl"
    monkeypatch.setenv("AGENT_TRACE_PATH", str(trace_path))
    context = [{"text": "Ventana estándar: 30 días.", "source_document": "returns.md"}]
    graph = build_agent_graph(
        retrieve_fn=lambda _question: context,
        generate_fn=lambda _question, chunks: chunks[0]["text"],
    )

    result = asyncio.run(invoke_agent(graph, "¿Cuál es la ventana?", "test-run-1"))

    trace = json.loads(trace_path.read_text(encoding="utf-8"))
    node_names = [event["node"] for event in trace["events"]]
    assert result["answer"] == "Ventana estándar: 30 días."
    assert node_names == ["validate_question", "retrieve", "generate_answer"]
    assert trace["run_id"] == "test-run-1"
    assert trace["events"][1]["output"]["context"] == context
    assert trace["answer"] == result["answer"]