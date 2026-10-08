from __future__ import annotations

import asyncio
import time
from typing import Any
from urllib.parse import quote

import httpx

from trackflow_mcp.errors import UpstreamError
from trackflow_mcp.schemas import (
    IncidentBranch,
    IncidentCategory,
    IncidentListQuery,
    IncidentOrigin,
    IncidentRecord,
    IncidentStatus,
    IncidentStatusResult,
    InventoryRecord,
)
from trackflow_mcp.settings import settings


class TrackFlowAPI:
    """HTTP client for the active TrackFlow domain API routes."""

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._client = client or httpx.AsyncClient(
            base_url=settings.trackflow_api_base_url.rstrip("/"), timeout=5.0
        )
        self._owns_client = client is None
        self._service_token: str | None = None
        self._service_token_expires_at = 0.0
        self._token_lock = asyncio.Lock()

    async def aclose(self) -> None:
        if self._owns_client:
            await self._client.aclose()

    async def _get_service_token(self) -> str:
        if self._service_token and time.monotonic() < self._service_token_expires_at:
            return self._service_token

        async with self._token_lock:
            if self._service_token and time.monotonic() < self._service_token_expires_at:
                return self._service_token
            if not settings.trackflow_service_username or not settings.trackflow_service_password:
                raise UpstreamError(
                    "UPSTREAM_AUTH_NOT_CONFIGURED",
                    "TrackFlow service account credentials are not configured.",
                )

            try:
                response = await self._client.post(
                    "/auth/login",
                    json={
                        "email": settings.trackflow_service_username,
                        "password": settings.trackflow_service_password,
                    },
                )
                response.raise_for_status()
                token = response.json()["access_token"]
            except (httpx.HTTPError, KeyError, ValueError) as error:
                raise UpstreamError(
                    "UPSTREAM_AUTH_FAILED",
                    "Could not authenticate the MCP service account to TrackFlow API.",
                ) from error

            self._service_token = token
            self._service_token_expires_at = time.monotonic() + 25 * 60
            return token

    async def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict[str, str] | None = None,
        json: dict[str, Any] | None = None,
        authenticated: bool = False,
        bad_request_code: str = "INVALID_ARGUMENT",
    ) -> Any:
        headers: dict[str, str] = {}
        if authenticated:
            headers["Authorization"] = f"Bearer {await self._get_service_token()}"
        try:
            response = await self._client.request(
                method, path, params=params, json=json, headers=headers
            )
            if response.status_code == 404:
                raise UpstreamError("NOT_FOUND", "The requested company record was not found.")
            if response.status_code == 400:
                raise UpstreamError(
                    bad_request_code,
                    _api_error_message(response, "The requested operation is not allowed."),
                )
            response.raise_for_status()
            return response.json()
        except UpstreamError:
            raise
        except httpx.TimeoutException as error:
            raise UpstreamError("UPSTREAM_TIMEOUT", "TrackFlow API request timed out.") from error
        except (httpx.HTTPError, ValueError) as error:
            raise UpstreamError(
                "UPSTREAM_UNAVAILABLE", "TrackFlow API could not complete the request."
            ) from error

    async def create_incident(
        self,
        *,
        title: str,
        description: str,
        category: IncidentCategory,
        status: IncidentStatus,
        origin: IncidentOrigin,
        branch: IncidentBranch,
    ) -> IncidentRecord:
        result = await self._request(
            "POST",
            "/api/incidents",
            json={
                "title": title,
                "description": description,
                "category": category.value,
                "status": status.value,
                "origin": origin.value,
                "branch": branch.value,
            },
            authenticated=True,
        )
        return IncidentRecord.model_validate(result)

    async def update_incident_status(
        self, incident_id: str, status: IncidentStatus
    ) -> IncidentStatusResult:
        result = await self._request(
            "PATCH",
            f"/api/incidents/{quote(incident_id, safe='')}/status",
            json={"status": status.value},
            authenticated=True,
            bad_request_code="INVALID_TRANSITION",
        )
        return IncidentStatusResult.model_validate(result)

    async def get_incident(self, incident_id: str) -> IncidentRecord:
        result = await self._request(
            "GET",
            f"/api/incidents/{quote(incident_id, safe='')}",
            authenticated=True,
        )
        return IncidentRecord.model_validate(result)

    async def list_incidents(self, filters: IncidentListQuery) -> list[IncidentRecord]:
        params = {
            key: value.value
            for key, value in filters.model_dump(exclude_none=True).items()
        }
        result = await self._request(
            "GET", "/api/incidents", params=params, authenticated=True
        )
        return [IncidentRecord.model_validate(row) for row in result]

    async def search_inventory(self, query: str) -> list[InventoryRecord]:
        result = await self._request("GET", "/inventory/products")
        normalized_query = query.casefold()
        products = [InventoryRecord.model_validate(row) for row in result]
        return [
            product
            for product in products
            if normalized_query in product.name.casefold()
            or normalized_query in product.sku_code.casefold()
            or normalized_query == product.id.casefold()
        ]


def _api_error_message(response: httpx.Response, fallback: str) -> str:
    try:
        body = response.json()
    except ValueError:
        return fallback
    detail = body.get("detail")
    if isinstance(detail, dict):
        details = detail.get("details") or []
        if details and isinstance(details[0], dict):
            return str(details[0].get("message", fallback))
        return str(detail.get("error", fallback))
    if isinstance(detail, list) and detail:
        return str(detail[0].get("message", fallback))
    return str(detail or fallback)