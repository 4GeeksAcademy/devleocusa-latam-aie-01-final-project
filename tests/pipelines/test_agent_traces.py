from __future__ import annotations

import json
from pathlib import Path

import pytest

TRACE_FIXTURE = Path(__file__).parent / "fixtures" / "agent_traces.json"


@pytest.fixture(scope="module")
def traces() -> dict[str, dict]:
    with TRACE_FIXTURE.open(encoding="utf-8") as trace_file:
        return {trace["run_id"]: trace for trace in json.load(trace_file)}


def test_empty_question_trace_ends_without_retrieval(traces) -> None:
    trace = traces["eval-empty-question"]
    node_names = [event["node"] for event in trace["events"]]

    assert "retrieve" not in node_names
    assert node_names[-1] == "invalid_question"
    assert trace["answer"] == "La pregunta no puede estar vacía."


def test_empty_retrieval_trace_abstains_without_generation(traces) -> None:
    trace = traces["eval-no-context"]
    node_names = [event["node"] for event in trace["events"]]
    retrieval = next(event for event in trace["events"] if event["node"] == "retrieve")

    assert retrieval["output"]["context"] == []
    assert "no_context" in node_names
    assert "generate_answer" not in node_names
    assert "No encontré información relevante" in trace["answer"]


def test_returns_answer_is_grounded_in_the_company_policy_trace(traces) -> None:
    trace = traces["eval-returns-policy"]
    node_names = [event["node"] for event in trace["events"]]
    retrieval_index = node_names.index("retrieve")
    generation_index = node_names.index("generate_answer")
    retrieved_context = trace["events"][retrieval_index]["output"]["context"]

    assert retrieval_index < generation_index
    assert any(
        chunk["source_document"] == "trackflow-returns-policy.es.md"
        for chunk in retrieved_context
    )
    assert any(chunk["_score"] >= 0.3 for chunk in retrieved_context)
    assert "30 días" in trace["answer"]