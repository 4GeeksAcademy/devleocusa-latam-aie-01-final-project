"""HTTP and wire-format tests for authenticated RFP SSE notifications."""

from __future__ import annotations

import json
import asyncio
from types import SimpleNamespace

from fastapi.testclient import TestClient


def _test_app(*, authenticated: bool = False):
    from fastapi import FastAPI
    from src.routes.rfp_router import rfp_events
    from src.services.auth_service import get_current_user
    from types import SimpleNamespace

    app = FastAPI()
    app.add_api_route("/rfp/events", rfp_events, methods=["GET"])
    if authenticated:
        app.dependency_overrides[get_current_user] = lambda: SimpleNamespace(id="test-user")
    return app


def test_rfp_sse_requires_authentication():
    app = _test_app(authenticated=False)

    response = TestClient(app).get("/rfp/events")

    assert response.status_code == 401


def test_rfp_sse_headers_and_named_wire_event(monkeypatch):
    from src.services.rfp_event_service import rfp_event_broker
    event = {
        "event": "rfp_ticket_created",
        "data": {
            "ticket_id": "tkt_test_01",
            "rfp_id": "rfp_test_01",
            "client_name": "Northline Apparel",
            "client_country": "US",
            "services_requested": ["warehouse", "lastmile"],
            "status": "analyzing",
            "created_at": "2026-07-24T14:32:00+00:00",
        },
    }

    from src.routes.rfp_router import rfp_events

    async def consume_actual_endpoint_stream():
        response = await rfp_events(_current_user=SimpleNamespace(id="test-user"))
        assert response.media_type == "text/event-stream"
        assert response.headers["cache-control"] == "no-cache, no-transform"
        assert response.headers["x-accel-buffering"] == "no"

        iterator = response.body_iterator
        first_frame = asyncio.create_task(iterator.__anext__())
        # Start the generator so it subscribes before publishing the test event.
        await asyncio.sleep(0)
        rfp_event_broker.publish(event)
        try:
            frame = await asyncio.wait_for(first_frame, timeout=1)
        finally:
            await iterator.aclose()
        return frame

    frame = asyncio.run(consume_actual_endpoint_stream())
    wire = frame.decode() if isinstance(frame, bytes) else frame
    assert wire.startswith("event: rfp_ticket_created\ndata: ")
    assert wire.endswith("\n\n")
    payload = json.loads(wire.split("data: ", 1)[1].split("\n", 1)[0])
    assert payload == event["data"]
    assert payload["ticket_id"] == "tkt_test_01"
    assert payload["status"] == "analyzing"
