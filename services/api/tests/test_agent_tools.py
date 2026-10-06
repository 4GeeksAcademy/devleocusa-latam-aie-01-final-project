from __future__ import annotations

import asyncio
from typing import Any

from src.agent.mcp_tools import AgentMCPTools
from src.agent.operational_tools import ToolStatus
from src.agent.state import IncidentLookupInput, InventoryLookupInput
from src.models.incident import IncidentStatus


class StubMCPTool:
    def __init__(self, result: dict[str, Any] | Exception) -> None:
        self.result = result
        self.arguments: dict[str, Any] | None = None

    async def ainvoke(self, arguments: dict[str, Any]):
        self.arguments = arguments
        if isinstance(self.result, Exception):
            raise self.result
        return "", {"structured_content": self.result}


class TextMCPTool:
    def __init__(self, result: dict[str, Any]) -> None:
        self.result = result

    async def ainvoke(self, _arguments: dict[str, Any]):
        import json

        return [{"type": "text", "text": json.dumps(self.result)}]


def test_incident_lookup_calls_discovered_mcp_tool_by_company_id() -> None:
    client = AgentMCPTools()
    tool = StubMCPTool(
        {
            "id": "ticket-42",
            "title": "Retraso de envío",
            "description": "Paquete demorado",
            "category": "Ultima_Milla",
            "status": "open",
            "origin": "customer",
            "branch": "Zaragoza",
            "created_at": "2026-10-01T12:00:00Z",
            "updated_at": "2026-10-01T12:00:00Z",
        }
    )
    client._tools = {"get_incident": tool}

    result = asyncio.run(
        client.lookup_incidents(IncidentLookupInput(ticket_id="ticket-42"))
    )

    assert tool.arguments == {"incident_id": "ticket-42"}
    assert result.status == ToolStatus.SUCCESS
    assert result.incidents[0].id == "ticket-42"
    assert result.incidents[0].status.value == "open"


def test_incident_lookup_passes_exact_company_filter_values() -> None:
    client = AgentMCPTools()
    tool = StubMCPTool({"incidents": []})
    client._tools = {"list_incidents": tool}

    result = asyncio.run(
        client.lookup_incidents(IncidentLookupInput(status=IncidentStatus.OPEN))
    )

    assert tool.arguments == {"status": "open"}
    assert result.status == ToolStatus.NOT_FOUND


def test_inventory_lookup_uses_structured_live_stock_result() -> None:
    client = AgentMCPTools()
    tool = StubMCPTool(
        {
            "products": [
                {
                    "id": "sku-1",
                    "name": "Cable USB",
                    "sku_code": "CBL-001",
                    "warehouse": "Zaragoza",
                    "current_stock": 12,
                }
            ]
        }
    )
    client._tools = {"search_inventory": tool}

    result = asyncio.run(
        client.lookup_inventory(InventoryLookupInput(product_query="CBL-001"))
    )

    assert tool.arguments == {"query": "CBL-001"}
    assert result.status == ToolStatus.SUCCESS
    assert result.products[0].current_stock == 12


def test_inventory_lookup_accepts_json_text_content_from_mcp() -> None:
    client = AgentMCPTools()
    client._tools = {"search_inventory": TextMCPTool({"products": []})}

    result = asyncio.run(
        client.lookup_inventory(InventoryLookupInput(product_query="CBL-001"))
    )

    assert result.status == ToolStatus.NOT_FOUND
    assert result.products == []


def test_mcp_transport_failure_returns_unavailable_result() -> None:
    client = AgentMCPTools()
    client._tools = {"get_incident": StubMCPTool(RuntimeError("connection failed"))}

    result = asyncio.run(
        client.lookup_incidents(IncidentLookupInput(ticket_id="ticket-42"))
    )

    assert result.status == ToolStatus.UNAVAILABLE
    assert result.message == "mcp_service_unavailable"