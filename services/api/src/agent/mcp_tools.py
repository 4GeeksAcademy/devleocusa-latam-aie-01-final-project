from __future__ import annotations

import asyncio
import json
import os
import time
from typing import Any

import httpx
from langchain_mcp_adapters.client import MultiServerMCPClient

from src.agent.operational_tools import (
    IncidentLookupResult,
    IncidentRecord,
    InventoryLookupResult,
    InventoryRecord,
    ToolStatus,
)
from src.agent.state import IncidentLookupInput, InventoryLookupInput


class OAuthClientCredentials(httpx.Auth):
    def __init__(
        self, token_transport: httpx.AsyncBaseTransport | None = None
    ) -> None:
        self.token_url = os.getenv("MCP_OAUTH_TOKEN_URL", "").strip()
        self.client_id = os.getenv("MCP_OAUTH_CLIENT_ID", "").strip()
        self.client_secret = os.getenv("MCP_OAUTH_CLIENT_SECRET", "").strip()
        self.scopes = os.getenv(
            "MCP_OAUTH_SCOPES", "trackflow:mcp incidents:read inventory:read"
        ).strip()
        self._token: str | None = None
        self._expires_at = 0.0
        self._lock = asyncio.Lock()
        self._token_transport = token_transport

    async def _get_token(self) -> str:
        if self._token and time.monotonic() < self._expires_at:
            return self._token
        async with self._lock:
            if self._token and time.monotonic() < self._expires_at:
                return self._token
            if not self.token_url or not self.client_id or not self.client_secret:
                raise RuntimeError("MCP OAuth client credentials are not configured.")
            try:
                async with httpx.AsyncClient(
                    timeout=5.0, transport=self._token_transport
                ) as client:
                    response = await client.post(
                        self.token_url,
                        data={
                            "grant_type": "client_credentials",
                            "client_id": self.client_id,
                            "client_secret": self.client_secret,
                            "scope": self.scopes,
                        },
                    )
                    response.raise_for_status()
                    token_response = response.json()
                    access_token = token_response["access_token"]
                    expires_in = int(token_response.get("expires_in", 300))
            except (httpx.HTTPError, KeyError, ValueError) as error:
                raise RuntimeError("Could not obtain an OAuth token for the MCP server.") from error

            self._token = access_token
            self._expires_at = time.monotonic() + max(1, expires_in - 30)
            return access_token

    async def async_auth_flow(self, request: httpx.Request):
        request.headers["Authorization"] = f"Bearer {await self._get_token()}"
        yield request


class AgentMCPTools:
    def __init__(self) -> None:
        server_url = os.getenv("MCP_SERVER_URL", "http://mcp:8001/mcp").strip()
        self._client = MultiServerMCPClient(
            {
                "trackflow": {
                    "transport": "streamable_http",
                    "url": server_url,
                    "auth": OAuthClientCredentials(),
                }
            },
            handle_tool_errors=False,
        )
        self._tools: dict[str, Any] = {}

    async def start(self) -> None:
        tools = await self._client.get_tools(server_name="trackflow")
        self._tools = {tool.name: tool for tool in tools}
        required = {"get_incident", "list_incidents", "search_inventory"}
        missing = required - self._tools.keys()
        if missing:
            raise RuntimeError(f"MCP server is missing required tools: {sorted(missing)}")

    async def aclose(self) -> None:
        self._tools.clear()

    async def lookup_incidents(
        self, query: IncidentLookupInput
    ) -> IncidentLookupResult:
        try:
            if query.ticket_id:
                payload = await self._invoke(
                    "get_incident", {"incident_id": query.ticket_id}
                )
                records = [IncidentRecord.model_validate(payload)]
            else:
                filters = query.model_dump(mode="json", exclude_none=True)
                payload = await self._invoke("list_incidents", filters)
                records = [
                    IncidentRecord.model_validate(item)
                    for item in payload.get("incidents", [])
                ]
        except Exception as error:
            if "NOT_FOUND" in str(error):
                return IncidentLookupResult(status=ToolStatus.NOT_FOUND, incidents=[])
            return IncidentLookupResult(
                status=ToolStatus.UNAVAILABLE,
                incidents=[],
                message="mcp_service_unavailable",
            )
        status = ToolStatus.SUCCESS if records else ToolStatus.NOT_FOUND
        return IncidentLookupResult(status=status, incidents=records)

    async def lookup_inventory(
        self, query: InventoryLookupInput
    ) -> InventoryLookupResult:
        try:
            payload = await self._invoke(
                "search_inventory", {"query": query.product_query}
            )
            records = [
                InventoryRecord.model_validate(item)
                for item in payload.get("products", [])
            ]
        except Exception:
            return InventoryLookupResult(
                status=ToolStatus.UNAVAILABLE,
                products=[],
                message="mcp_service_unavailable",
            )
        status = ToolStatus.SUCCESS if records else ToolStatus.NOT_FOUND
        return InventoryLookupResult(status=status, products=records)

    async def _invoke(self, name: str, arguments: dict[str, Any]) -> dict[str, Any]:
        tool = self._tools.get(name)
        if tool is None:
            raise RuntimeError(f"MCP tool {name!r} was not discovered.")
        result = await tool.ainvoke(arguments)
        if isinstance(result, tuple) and len(result) == 2:
            _content, artifact = result
            if isinstance(artifact, dict):
                structured_content = artifact.get("structured_content")
                if isinstance(structured_content, dict):
                    return structured_content
        if isinstance(result, dict):
            return result
        if isinstance(result, list):
            for content_block in result:
                if not isinstance(content_block, dict) or content_block.get("type") != "text":
                    continue
                try:
                    payload = json.loads(content_block.get("text", ""))
                except (TypeError, json.JSONDecodeError):
                    continue
                if isinstance(payload, dict):
                    return payload
        raise ValueError(f"MCP tool {name!r} returned no structured content.")