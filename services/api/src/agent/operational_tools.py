from __future__ import annotations

import os
from datetime import datetime
from enum import Enum
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from src.agent.state import IncidentLookupInput, InventoryLookupInput
from src.models.incident import IncidentBranch, IncidentCategory, IncidentOrigin, IncidentStatus

TOOL_HTTP_TIMEOUT_SECONDS = 4.0


class ToolStatus(str, Enum):
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    UNAVAILABLE = "unavailable"


class IncidentRecord(BaseModel):
    id: str
    title: str
    description: str | None = None
    category: IncidentCategory
    status: IncidentStatus
    origin: IncidentOrigin
    branch: IncidentBranch
    created_at: datetime
    updated_at: datetime | None = None


class IncidentLookupResult(BaseModel):
    status: ToolStatus
    incidents: list[IncidentRecord]
    message: str | None = None


class InventoryRecord(BaseModel):
    id: str
    name: str
    sku_code: str
    warehouse: str
    current_stock: int


class InventoryLookupResult(BaseModel):
    status: ToolStatus
    products: list[InventoryRecord]
    message: str | None = None


def _http_client() -> httpx.Client:
    return httpx.Client(timeout=TOOL_HTTP_TIMEOUT_SECONDS)


def _base_url() -> str:
    return os.getenv("TRACKFLOW_API_BASE_URL", "http://127.0.0.1:8000").rstrip("/")


def _headers(authorization: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {authorization}"} if authorization else {}


def _incident_unavailable(message: str) -> IncidentLookupResult:
    return IncidentLookupResult(
        status=ToolStatus.UNAVAILABLE,
        incidents=[],
        message=message,
    )


def _inventory_unavailable(message: str) -> InventoryLookupResult:
    return InventoryLookupResult(
        status=ToolStatus.UNAVAILABLE,
        products=[],
        message=message,
    )


def lookup_incidents(
    query: IncidentLookupInput,
    authorization: str,
) -> IncidentLookupResult:
    """Read incidents through the authenticated API; never mutate ticket data."""
    try:
        criteria = IncidentLookupInput.model_validate(query)
        with _http_client() as client:
            if criteria.ticket_id:
                response = client.get(
                    f"{_base_url()}/api/incidents/{quote(criteria.ticket_id, safe='')}",
                    headers=_headers(authorization),
                )
                if response.status_code == 404:
                    return IncidentLookupResult(
                        status=ToolStatus.NOT_FOUND,
                        incidents=[],
                    )
                response.raise_for_status()
                incidents = [IncidentRecord.model_validate(response.json())]
            else:
                filters = criteria.model_dump(mode="json", exclude_none=True)
                response = client.get(
                    f"{_base_url()}/api/incidents",
                    params=filters,
                    headers=_headers(authorization),
                )
                response.raise_for_status()
                incidents = [IncidentRecord.model_validate(row) for row in response.json()]
    except httpx.TimeoutException:
        return _incident_unavailable("timeout")
    except (httpx.RequestError, httpx.HTTPStatusError):
        return _incident_unavailable("service_unavailable")
    except (ValidationError, ValueError, TypeError):
        return _incident_unavailable("invalid_response")

    status = ToolStatus.SUCCESS if incidents else ToolStatus.NOT_FOUND
    return IncidentLookupResult(status=status, incidents=incidents)


def lookup_inventory(
    product_query: InventoryLookupInput,
    authorization: str,
) -> InventoryLookupResult:
    """Find matching products from the live API response with computed stock."""
    try:
        criteria = InventoryLookupInput.model_validate(product_query)
        query = criteria.product_query.strip().casefold()
        if not query:
            raise ValueError("product_query es obligatorio")
        with _http_client() as client:
            response = client.get(
                f"{_base_url()}/inventory/products",
                headers=_headers(authorization),
            )
            response.raise_for_status()
            products = [InventoryRecord.model_validate(row) for row in response.json()]
        matches = [
            product
            for product in products
            if query in product.name.casefold()
            or query in product.sku_code.casefold()
            or query == product.id.casefold()
        ]
    except httpx.TimeoutException:
        return _inventory_unavailable("timeout")
    except (httpx.RequestError, httpx.HTTPStatusError):
        return _inventory_unavailable("service_unavailable")
    except (ValidationError, ValueError, TypeError):
        return _inventory_unavailable("invalid_response")

    status = ToolStatus.SUCCESS if matches else ToolStatus.NOT_FOUND
    return InventoryLookupResult(status=status, products=matches)