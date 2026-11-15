from datetime import datetime, timezone

from sqlalchemy import update
from sqlmodel import Session, SQLModel, create_engine
from sqlalchemy.pool import StaticPool

from src.models.audit_log import AuditLogEntry
from src.services.audit_log_service import append_event, list_events, verify_chain


def _engine():
    engine = create_engine("sqlite://", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    SQLModel.metadata.create_all(engine)
    return engine


def _append(session, **overrides):
    payload = {
        "actor_id": "user-1",
        "actor_type": "human",
        "actor_name": "Ana",
        "action": "inventory.manual_adjustment",
        "resource_type": "sku",
        "resource_id": "sku-1",
        "source": "127.0.0.1",
        "department": "Operaciones de Almacén",
        "country": "España",
        "warehouse_id": "warehouse-zaragoza",
        "details": {"quantity_delta": 3},
    }
    payload.update(overrides)
    return append_event(session, **payload)


def test_appended_events_form_a_verifiable_chain_and_keep_actor_context():
    engine = _engine()
    with Session(engine) as session:
        first = _append(session)
        second = _append(session, action="user.updated", resource_type="user", resource_id="user-2")
        session.commit()
        assert first.actor_id == "user-1"
        assert first.warehouse_id == "warehouse-zaragoza"
        assert second.previous_hash == first.event_hash
        assert verify_chain(session) == {"valid": True, "checked": 2, "event_id": None, "reason": None}


def test_verifier_detects_tampering():
    engine = _engine()
    with Session(engine) as session:
        event = _append(session)
        session.commit()
        session.execute(update(AuditLogEntry).where(AuditLogEntry.id == event.id).values(details_json='{"quantity_delta":999}'))
        session.commit()
        assert verify_chain(session)["reason"] == "event_hash_mismatch"


def test_event_filters_and_pagination():
    engine = _engine()
    with Session(engine) as session:
        _append(session, actor_id="a", action="inventory.manual_adjustment", occurred_at=datetime(2025, 1, 1, tzinfo=timezone.utc))
        _append(session, actor_id="b", action="user.updated", resource_type="user", resource_id="u2", department="Personas", occurred_at=datetime(2025, 1, 2, tzinfo=timezone.utc))
        _append(session, actor_id="c", action="inventory.manual_adjustment", occurred_at=datetime(2025, 1, 3, tzinfo=timezone.utc))
        session.commit()
        events = list_events(session, action="inventory.manual_adjustment", department="Operaciones de Almacén", limit=1, offset=1)
        assert len(events) == 1
        assert events[0].actor_id == "a"
        assert verify_chain(session)["valid"]


def test_country_and_warehouse_must_be_paired():
    engine = _engine()
    with Session(engine) as session:
        try:
            _append(session, warehouse_id=None)
        except ValueError as exc:
            assert "supplied together" in str(exc)
        else:
            raise AssertionError("Expected paired warehouse context validation")
