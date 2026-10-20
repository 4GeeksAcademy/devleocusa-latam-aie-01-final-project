from __future__ import annotations

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from rfp_intake.approval import (
    arbitrate_conflicts,
    build_department_approval_graph,
    invoke_department_approval,
    validate_decision,
)


def make_graph(max_iterations=3, on_trace=None):
    calls = []

    def generate(department, workstream, summary, feedback):
        calls.append((department, feedback))
        return f"{department} draft {len(calls)} {feedback}".strip()

    def evaluate(department, draft, aspects):
        return {"overall_pass": True, "draft": draft}

    graph = build_department_approval_graph(
        checkpointer=InMemorySaver(), generator=generate, evaluator=evaluate,
        max_iterations=max_iterations,
        on_trace=on_trace,
    )
    return graph, calls


def invoke(graph, dept, **extra):
    return invoke_department_approval(
        graph, ticket_id="ticket-1", department_id=dept,
        workstream={"department": dept, "key_aspects": {}}, summary="brief",
        generator=lambda *args: "generated", evaluator=lambda *args: {"overall_pass": True},
        **extra,
    )


def test_departments_pause_and_resume_independently():
    graph, calls = make_graph()
    warehouse = invoke(graph, "warehouse", initial_draft="warehouse v2", initial_iteration_count=2)
    lastmile = invoke(graph, "lastmile", initial_draft="lastmile v1", initial_iteration_count=1)
    assert warehouse["draft"] == "warehouse v2"
    assert lastmile["draft"] == "lastmile v1"
    assert warehouse["__interrupt__"][0].value["department_id"] == "warehouse"
    assert lastmile["__interrupt__"][0].value["department_id"] == "lastmile"
    assert not calls

    warehouse = invoke(graph, "warehouse", resume={"decision": "approve"})
    assert warehouse["approval_status"] == "approved"
    state = invoke(graph, "lastmile", resume={"decision": "request_changes", "comment": "keep going"})
    assert state["approval_status"] == "pending"
    assert state["draft"].startswith("lastmile draft")


def test_request_changes_regenerates_only_own_branch_and_counts_attempt():
    graph, calls = make_graph()
    invoke(graph, "warehouse", initial_draft="original", initial_iteration_count=1)
    invoke(graph, "lastmile", initial_draft="peer", initial_iteration_count=1)
    resumed = invoke(graph, "warehouse", resume={"decision": "request_changes", "comment": "clarify capacity"})
    assert resumed["draft"].startswith("warehouse draft")
    assert resumed["iteration_count"] == 2
    assert calls == [("warehouse", "clarify capacity")]
    assert resumed["__interrupt__"][0].value["department_id"] == "warehouse"
    peer = invoke(graph, "lastmile", resume={"decision": "request_changes", "comment": "peer feedback"})
    assert peer["draft"].startswith("lastmile draft")
    assert peer["approval_status"] == "pending"


def test_iteration_limit_stops_regeneration():
    graph, calls = make_graph(max_iterations=2)
    invoke(graph, "warehouse", initial_draft="last allowed", initial_iteration_count=2)
    result = invoke(graph, "warehouse", resume={"decision": "request_changes", "comment": "change"})
    assert result["approval_status"] == "needs_human_review"
    assert calls == []


def test_decision_validation_and_deterministic_conflicts():
    with pytest.raises(ValueError):
        validate_decision({"decision": "request_changes", "comment": " "})
    with pytest.raises(ValueError):
        validate_decision({"decision": "anything"})

    result = arbitrate_conflicts([
        {"department_id": "warehouse", "committed_capacity": 4000, "currency": "EUR"},
        {"department_id": "lastmile", "assumed_monthly_volume": 5000, "currency": "USD"},
        {"department_id": "reverse", "returns_turnaround_hours": 24, "currency": "USD"},
    ], client_country="Spain")
    assert {conflict["trigger_id"] for conflict in result["conflicts"]} == {
        "volume-vs-capacity", "returns-sla-breach", "currency-mismatch"
    }
    assert result["blocked"]


def test_trace_callback_records_approval_request_and_decision():
    events = []
    graph, _ = make_graph(on_trace=events.append)
    invoke(graph, "warehouse", initial_draft="draft")
    assert [event["node"] for event in events] == ["prepare_for_approval", "approval_requested"]
    assert events[0]["ticket_id"] == "ticket-1"
    assert events[0]["department_id"] == "warehouse"

    invoke(graph, "warehouse", resume={"decision": "approve"})
    # LangGraph replays the interrupting node on resume; persistence deduplicates
    # the repeated request event while retaining the human decision.
    assert [event["node"] for event in events] == [
        "prepare_for_approval", "approval_requested", "approval_requested", "human_approval"
    ]
