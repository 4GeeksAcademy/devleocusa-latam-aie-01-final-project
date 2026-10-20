"""Focused safety tests for RFP test approvers and targeted dispatch."""

from __future__ import annotations

from types import SimpleNamespace

import pytest


def test_test_approver_requires_opt_in_and_active_user(monkeypatch):
    from src.services import rfp_service

    monkeypatch.delenv("RFP_APPROVER_WAREHOUSE_EMAIL", raising=False)
    monkeypatch.setenv("RFP_TEST_APPROVER_WAREHOUSE_EMAIL", "warehouse.qa@trackflow.example")
    monkeypatch.setenv("RFP_ALLOW_TEST_APPROVERS", "false")
    with pytest.raises(PermissionError):
        rfp_service._approver_email("warehouse")

    monkeypatch.setenv("RFP_ALLOW_TEST_APPROVERS", "true")
    monkeypatch.setenv("RFP_APPROVER_TEST_TICKET_ID", "synthetic-ticket")
    monkeypatch.setattr(rfp_service, "get_user_by_email", lambda email: None)
    with pytest.raises(PermissionError, match="no está registrada y activa"):
        rfp_service._approver_email("warehouse")

    monkeypatch.setattr(rfp_service, "get_user_by_email", lambda email: SimpleNamespace(is_active=False))
    with pytest.raises(PermissionError, match="no está registrada y activa"):
        rfp_service._approver_email("warehouse")

    monkeypatch.setattr(rfp_service, "get_user_by_email", lambda email: SimpleNamespace(is_active=True))
    assert rfp_service._approver_email("warehouse") == "warehouse.qa@trackflow.example"

    monkeypatch.setenv("RFP_APPROVER_WAREHOUSE_EMAIL", "ana@trackflow.example")
    assert rfp_service._approver_email("warehouse") == "ana@trackflow.example"


def test_test_approver_cannot_decide_non_designated_ticket(monkeypatch):
    from src.models.rfp import RFPTicket
    from src.services import rfp_service

    monkeypatch.setenv("RFP_ALLOW_TEST_APPROVERS", "true")
    monkeypatch.setenv("RFP_APPROVER_TEST_TICKET_ID", "synthetic-ticket")
    monkeypatch.setattr(rfp_service, "_approver_email", lambda department: "warehouse.qa@trackflow.example")
    class FakeSession:
        def get(self, model, ticket_id):
            return RFPTicket(id=ticket_id, original_filename="synthetic.pdf", pdf_path="/tmp/synthetic.pdf")
        def exec(self, statement):
            raise AssertionError("test-ticket guard must run before querying sections")
    session = FakeSession()
    with pytest.raises(PermissionError, match="ticket sintético configurado"):
        rfp_service.submit_department_decision(
            session, ticket_id="real-ticket", department_id="warehouse",
            user_email="warehouse.qa@trackflow.example", decision={"decision": "approve"},
        )


def test_targeted_dispatch_does_not_fall_back_to_another_ticket(monkeypatch):
    from src.models.rfp import RFPTicket
    from src.services import rfp_service

    statements = []
    class FakeSession:
        def exec(self, statement):
            statements.append(statement)
            return SimpleNamespace(first=lambda: None)

    assert rfp_service.claim_next_proposal_ticket(FakeSession(), ticket_id="chosen-ticket") is None
    assert len(statements) == 1
    statement = statements[0]
    where_criteria = statement._where_criteria
    assert any("chosen-ticket" in str(criterion.compile().params.values()) for criterion in where_criteria)


def test_trace_persistence_writes_incremental_trace_records():
    from datetime import datetime, timezone

    from src.services import rfp_service

    class FakeSession:
        def __init__(self):
            self.added = []
            self.commits = 0

        def exec(self, statement):
            # No existing duplicate trace and no prior sequence for this thread.
            return SimpleNamespace(first=lambda: None)

        def add(self, record):
            self.added.append(record)

        def commit(self):
            self.commits += 1

    session = FakeSession()
    rfp_service._persist_trace_event(session, "synthetic-ticket", {
        "node": "prepare_for_approval",
        "agent": "proposal_agent:warehouse",
        "thread_id": "rfp-synthetic-ticket:warehouse",
        "department_id": "warehouse",
        "input": {"department": "warehouse"},
        "output": {"status": "pending"},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })
    assert len(session.added) == 1
    record = session.added[0]
    assert record.ticket_id == "synthetic-ticket"
    assert record.department_id == "warehouse"
    assert record.thread_id == "rfp-synthetic-ticket:warehouse"
    assert record.sequence == 1
    assert record.node == "prepare_for_approval"
    assert session.commits == 1
