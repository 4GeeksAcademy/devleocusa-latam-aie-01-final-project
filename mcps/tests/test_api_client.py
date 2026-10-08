from __future__ import annotations

import asyncio
import json
import time

import httpx

from trackflow_mcp.api_client import TrackFlowAPI
from trackflow_mcp.schemas import (
    IncidentBranch,
    IncidentCategory,
    IncidentOrigin,
    IncidentStatus,
)


def test_incident_creation_uses_trackflow_field_names_and_enums() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "POST"
        assert request.url.path == "/api/incidents"
        assert json.loads(request.content) == {
            "title": "Delay",
            "description": "Shipment delayed",
            "category": "Ultima_Milla",
            "status": "open",
            "origin": "customer",
            "branch": "Zaragoza",
        }
        return httpx.Response(
            201,
            json={
                "id": "ticket-42",
                "title": "Delay",
                "description": "Shipment delayed",
                "category": "Ultima_Milla",
                "status": "open",
                "origin": "customer",
                "branch": "Zaragoza",
                "created_at": "2026-10-01T12:00:00Z",
                "updated_at": "2026-10-01T12:00:00Z",
            },
        )

    async def create() -> None:
        client = httpx.AsyncClient(
            base_url="http://trackflow.test",
            transport=httpx.MockTransport(handler),
        )
        api = TrackFlowAPI(client)
        api._service_token = "internal-api-token"
        api._service_token_expires_at = time.monotonic() + 60
        try:
            result = await api.create_incident(
                title="Delay",
                description="Shipment delayed",
                category=IncidentCategory.ULTIMA_MILLA,
                status=IncidentStatus.OPEN,
                origin=IncidentOrigin.CUSTOMER,
                branch=IncidentBranch.ZARAGOZA,
            )
            assert result.id == "ticket-42"
        finally:
            await client.aclose()

    asyncio.run(create())


def test_status_updates_use_the_incidents_lifecycle_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "PATCH"
        assert request.url.path == "/api/incidents/ticket-42/status"
        assert request.read() == b'{"status":"in_progress"}'
        assert request.headers["Authorization"] == "Bearer internal-api-token"
        return httpx.Response(
            200,
            json={
                "id": "ticket-42",
                "status": "in_progress",
                "updated_at": "2026-10-01T12:00:00Z",
            },
        )

    async def update_status() -> None:
        client = httpx.AsyncClient(
            base_url="http://trackflow.test",
            transport=httpx.MockTransport(handler),
        )
        api = TrackFlowAPI(client)
        api._service_token = "internal-api-token"
        api._service_token_expires_at = time.monotonic() + 60
        try:
            result = await api.update_incident_status(
                "ticket-42", IncidentStatus.IN_PROGRESS
            )
            assert result.id == "ticket-42"
            assert result.status == IncidentStatus.IN_PROGRESS
        finally:
            await client.aclose()

    asyncio.run(update_status())


def test_inventory_search_uses_only_the_live_read_endpoint() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.method == "GET"
        assert request.url.path == "/inventory/products"
        assert "Authorization" not in request.headers
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

    async def search() -> None:
        client = httpx.AsyncClient(
            base_url="http://trackflow.test",
            transport=httpx.MockTransport(handler),
        )
        api = TrackFlowAPI(client)
        try:
            products = await api.search_inventory("cbl")
            assert len(products) == 1
            assert products[0].current_stock == 12
        finally:
            await client.aclose()

    asyncio.run(search())