from __future__ import annotations

import logging
from functools import wraps
from typing import Annotated, Any, Literal

from fastmcp import FastMCP
from fastmcp.exceptions import ToolError
from fastmcp.server.middleware import Middleware, MiddlewareContext
from mcpauth import AuthInfo
from pydantic import Field
from starlette.applications import Starlette
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from trackflow_mcp.api_client import TrackFlowAPI
from trackflow_mcp.auth import (
    mcp_auth,
    protected_resource_metadata,
    verify_access_token as verify_mcp_access_token,
)
from trackflow_mcp.errors import error_code
from trackflow_mcp.schemas import (
    IncidentBranch,
    IncidentCategory,
    IncidentListQuery,
    IncidentListResult,
    IncidentOrigin,
    IncidentRecord,
    IncidentStatus,
    IncidentStatusResult,
    InventoryRecord,
    InventorySearchResult,
)
from trackflow_mcp.settings import settings


logger = logging.getLogger("trackflow_mcp.tools")
logger.setLevel(logging.INFO)
api = TrackFlowAPI()
mcp = FastMCP(
    name="TrackFlow Company Tools",
    instructions=(
        "Manage TrackFlow Incidents Manager tickets and look up live inventory. "
        "Each tool documents its required scope and supported company values. "
        "Inventory is read-only; request_inventory_change always rejects writes."
    ),
)


def _require_scope(auth_info: AuthInfo | None, scope: str) -> str:
    if auth_info is None:
        raise ToolError("UNAUTHENTICATED: A valid OAuth access token is required.")
    if scope not in auth_info.scopes:
        raise ToolError(f"INSUFFICIENT_SCOPE: This tool requires the '{scope}' scope.")
    return auth_info.client_id or auth_info.subject


def _scoped_tool(scope: str):
    def decorate(function):
        @wraps(function)
        async def wrapped(*args, **kwargs):
            auth_info = mcp_auth.auth_info
            _require_scope(auth_info, scope)
            return await function(*args, **kwargs)

        return wrapped

    return decorate


class ToolAuditMiddleware(Middleware):
    async def on_call_tool(self, context: MiddlewareContext, call_next):
        tool_name = getattr(context.message, "name", "unknown")
        auth_info = mcp_auth.auth_info
        client_id = auth_info.client_id if auth_info else "unauthenticated"
        try:
            result = await call_next(context)
        except Exception as error:
            logger.info(
                "tool_invocation client=%s tool=%s result=error code=%s",
                client_id,
                tool_name,
                error_code(error),
            )
            raise

        if getattr(result, "isError", False):
            content = getattr(result, "content", [])
            message = " ".join(
                str(getattr(block, "text", "")) for block in content
            )
            logger.info(
                "tool_invocation client=%s tool=%s result=error code=%s",
                client_id,
                tool_name,
                error_code(RuntimeError(message)),
            )
        else:
            logger.info(
                "tool_invocation client=%s tool=%s result=success",
                client_id,
                tool_name,
            )
        return result


@mcp.tool(
    name="create_incident",
    description=(
        "Create a ticket in TrackFlow Incidents Manager. Requires incidents:create. "
        "Use the exact company category, status, origin, and branch values in the schema. "
        "Returns the created company incident including its id and timestamps."
    ),
)
@_scoped_tool("incidents:create")
async def create_incident(
    title: Annotated[str, Field(min_length=1, max_length=160)],
    description: Annotated[str, Field(min_length=1)],
    category: IncidentCategory,
    status: IncidentStatus,
    origin: IncidentOrigin,
    branch: IncidentBranch,
) -> IncidentRecord:
    return await api.create_incident(
        title=title,
        description=description,
        category=category,
        status=status,
        origin=origin,
        branch=branch,
    )


@mcp.tool(
    name="update_incident_status",
    description=(
        "Move an existing ticket through the Incidents Manager lifecycle. Requires "
        "incidents:status:write. Uses PATCH /api/incidents/{id}/status; transitions "
        "not allowed by the company lifecycle are rejected."
    ),
)
@_scoped_tool("incidents:status:write")
async def update_incident_status(
    incident_id: Annotated[str, Field(min_length=1, max_length=100)],
    status: IncidentStatus,
) -> IncidentStatusResult:
    return await api.update_incident_status(incident_id, status)


@mcp.tool(
    name="get_incident",
    description=(
        "Retrieve one ticket by its exact TrackFlow Incidents Manager id. Requires "
        "incidents:read. Returns the company incident fields and lifecycle status."
    ),
)
@_scoped_tool("incidents:read")
async def get_incident(
    incident_id: Annotated[str, Field(min_length=1, max_length=100)],
) -> IncidentRecord:
    return await api.get_incident(incident_id)


@mcp.tool(
    name="list_incidents",
    description=(
        "List Incidents Manager tickets matching one or more exact company filters. "
        "Requires incidents:read. At least one of status, origin, branch, or category "
        "must be provided; values are the enums declared in this tool schema."
    ),
)
@_scoped_tool("incidents:read")
async def list_incidents(
    status: IncidentStatus | None = None,
    origin: IncidentOrigin | None = None,
    branch: IncidentBranch | None = None,
    category: IncidentCategory | None = None,
) -> IncidentListResult:
    try:
        filters = IncidentListQuery(
            status=status,
            origin=origin,
            branch=branch,
            category=category,
        )
    except ValueError as error:
        raise ToolError("INVALID_ARGUMENT: Provide at least one incident filter.") from error
    return IncidentListResult(incidents=await api.list_incidents(filters))


@mcp.tool(
    name="search_inventory",
    description=(
        "Search current TrackFlow SKU inventory by a case-insensitive partial name or "
        "SKU code, or exact SKU id. Requires inventory:read. Returns id, name, "
        "sku_code, warehouse, and live current_stock calculated by the inventory API. "
        "This tool cannot change inventory."
    ),
)
@_scoped_tool("inventory:read")
async def search_inventory(
    query: Annotated[str, Field(min_length=1, max_length=200)],
) -> InventorySearchResult:
    if not query.strip():
        raise ToolError("INVALID_ARGUMENT: query must contain a product name, SKU code, or id.")
    return InventorySearchResult(products=await api.search_inventory(query.strip()))


@mcp.tool(
    name="request_inventory_change",
    description=(
        "Explicitly rejects inventory writes. This deny-only tool exists to communicate "
        "the read-only boundary; it never calls a write endpoint or changes data. "
        "Requires inventory:read. Supported operation labels are create_product, "
        "inbound_order, outbound_order, adjust_stock, and delete_product."
    ),
)
@_scoped_tool("inventory:read")
async def request_inventory_change(
    operation: Literal[
        "create_product",
        "inbound_order",
        "outbound_order",
        "adjust_stock",
        "delete_product",
    ],
    sku_id: Annotated[str | None, Field(min_length=1)] = None,
    quantity: Annotated[int | None, Field(ge=1)] = None,
) -> dict[str, str]:
    raise ToolError(
        "READ_ONLY: Inventory is read-only through this MCP server; "
        f"'{operation}' was not performed."
    )


async def _protected_resource(_request: Request) -> JSONResponse:
    return JSONResponse(protected_resource_metadata())


class BearerChallengeMiddleware(BaseHTTPMiddleware):
    async def dispatch(
        self, request: Request, call_next: RequestResponseEndpoint
    ) -> Response:
        response = await call_next(request)
        if response.status_code == 401:
            metadata_url = (
                f"{settings.mcp_public_url.rstrip('/')}/"
                ".well-known/oauth-protected-resource"
            )
            response.headers["WWW-Authenticate"] = (
                f'Bearer resource_metadata="{metadata_url}"'
            )
        return response


def create_app(verify_access_token=None) -> Starlette:
    mcp_http_app = mcp.http_app(
        path="/mcp",
        transport="streamable-http",
        stateless_http=True,
    )
    authenticated_app = mcp_auth.bearer_auth_middleware(
        verify_access_token or verify_mcp_access_token,
        audience=settings.mcp_audience,
        required_scopes=[settings.mcp_required_scope],
        show_error_details=False,
    )(mcp_http_app)
    protected_app = BearerChallengeMiddleware(authenticated_app)
    return Starlette(
        routes=[
            Route(
                "/.well-known/oauth-protected-resource",
                _protected_resource,
                methods=["GET"],
            ),
            Mount("/", app=protected_app),
        ],
        lifespan=mcp_http_app.router.lifespan_context,
    )


mcp.add_middleware(ToolAuditMiddleware())
app = create_app()

if __name__ == "__main__":
    import uvicorn

    uvicorn.run(app, host=settings.mcp_host, port=settings.mcp_port)