from __future__ import annotations

import httpx

from src.agent import operational_tools
from src.agent.operational_tools import ToolStatus
from src.agent.state import (
    IncidentLookupInput,
    InventoryLookupInput,
)
from src.models.incident import IncidentStatus


def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(
        operational_tools,
        "_http_client",
        lambda: httpx.Client(transport=httpx.MockTransport(handler)),
    )


def test_incident_tool_reads_ticket_using_bearer_token(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/incidents/ticket-42"
        assert request.headers["Authorization"] == "Bearer test-token"
        return httpx.Response(
            200,
            json={
                "id": "ticket-42",
                "title": "Retraso de envío",
                "description": "Paquete demorado",
                "category": "Ultima_Milla",
                "status": "open",
                "origin": "customer",
                "branch": "Zaragoza",
                "created_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-01T12:00:00Z",
            },
        )

    _mock_client(monkeypatch, handler)
    monkeypatch.setenv("TRACKFLOW_API_BASE_URL", "http://trackflow.test")

    result = operational_tools.lookup_incidents(
        IncidentLookupInput(ticket_id="ticket-42"), "test-token"
    )

    assert result.status == ToolStatus.SUCCESS
    assert result.incidents[0].status.value == "open"


def test_incident_tool_reports_not_found_and_timeout(monkeypatch) -> None:
    assert operational_tools.TOOL_HTTP_TIMEOUT_SECONDS == 4.0

    _mock_client(monkeypatch, lambda _request: httpx.Response(404))
    result = operational_tools.lookup_incidents(IncidentLookupInput(ticket_id="missing"), "token")
    assert result.status == ToolStatus.NOT_FOUND

    def timeout(_request):
        raise httpx.ReadTimeout("slow backend")

    _mock_client(monkeypatch, timeout)
    result = operational_tools.lookup_incidents(IncidentLookupInput(ticket_id="ticket-42"), "token")
    assert result.status == ToolStatus.UNAVAILABLE
    assert result.message == "timeout"


def test_incident_tool_sends_supported_list_filters(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/api/incidents"
        assert request.url.params["status"] == "open"
        assert request.headers["Authorization"] == "Bearer token"
        return httpx.Response(200, json=[])

    _mock_client(monkeypatch, handler)

    result = operational_tools.lookup_incidents(
        IncidentLookupInput(status=IncidentStatus.OPEN), "token"
    )

    assert result.status == ToolStatus.NOT_FOUND


def test_inventory_tool_returns_stock_from_live_api(monkeypatch) -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/inventory/products"
        return httpx.Response(
            200,
            json=[
                {
                    "id": "sku-1",
                    "name": "Cable USB",
                    "sku_code": "CBL-001",
                    "warehouse": "Zaragoza",
                    "current_stock": 12,
                }
            ],
        )

    _mock_client(monkeypatch, handler)

    result = operational_tools.lookup_inventory(
        InventoryLookupInput(product_query="CBL-001"), "token"
    )

    assert result.status == ToolStatus.SUCCESS
    assert result.products[0].current_stock == 12