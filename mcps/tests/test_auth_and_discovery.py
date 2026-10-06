from __future__ import annotations

import json
import logging

from mcpauth import AuthInfo
from mcpauth.exceptions import BearerAuthExceptionCode, MCPAuthBearerAuthException
from starlette.testclient import TestClient

from trackflow_mcp.server import create_app
from trackflow_mcp.auth import verify_access_token
from trackflow_mcp.settings import settings


def _verify_test_token(token: str) -> AuthInfo:
    if token == "invalid":
        raise MCPAuthBearerAuthException(BearerAuthExceptionCode.INVALID_TOKEN)
    scopes = token.removeprefix("scopes:").replace("+", " ").split()
    return AuthInfo(
        token=token,
        issuer="https://wrong-issuer.test" if token == "wrong-issuer" else settings.issuer,
        client_id="mcp-test-client",
        scopes=scopes,
        subject="mcp-test-subject",
        audience="wrong-audience" if token == "wrong-audience" else settings.mcp_audience,
        claims={"scope": " ".join(scopes)},
    )


def _request_rpc(client: TestClient, token: str | None, payload: dict):
    headers = {"Accept": "application/json, text/event-stream"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    response = client.post("/mcp", json=payload, headers=headers)
    if response.headers.get("content-type", "").startswith("text/event-stream"):
        data = next(
            line.removeprefix("data: ")
            for line in response.text.splitlines()
            if line.startswith("data: ")
        )
        return response, json.loads(data)
    return response, response.json() if response.content else None


def _initialize(client: TestClient, token: str) -> None:
    response, _ = _request_rpc(
        client,
        token,
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2025-03-26",
                "capabilities": {},
                "clientInfo": {"name": "mcp-contract-test", "version": "1"},
            },
        },
    )
    assert response.status_code == 200


def test_resource_metadata_is_discoverable_without_exposing_tools() -> None:
    with TestClient(create_app(_verify_test_token)) as client:
        response = client.get("/.well-known/oauth-protected-resource")
        assert response.status_code == 200
        assert response.json()["resource"] == settings.mcp_resource_url
        assert response.json()["authorization_servers"] == [settings.issuer]
        assert "openid" in response.json()["scopes_supported"]


def test_invalid_jwt_logs_safe_diagnostics_without_the_token(caplog) -> None:
    token = "not-a-real-access-token"
    caplog.set_level(logging.WARNING, logger="trackflow_mcp.auth")

    try:
        verify_access_token(token)
    except Exception:
        pass
    else:
        raise AssertionError("An invalid JWT must be rejected.")

    assert "access_token_rejected" in caplog.text
    assert "not-a-real-access-token" not in caplog.text


def test_tools_list_rejects_missing_or_invalid_bearer() -> None:
    with TestClient(create_app(_verify_test_token)) as client:
        response, _ = _request_rpc(
            client,
            None,
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 401
        assert response.json()["error"] == "missing_auth_header"
        assert "resource_metadata" in response.headers["www-authenticate"]

        response, _ = _request_rpc(
            client,
            "invalid",
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 401
        assert response.json()["error"] == "invalid_token"

        for token, expected_error in (
            ("wrong-issuer", "invalid_issuer"),
            ("wrong-audience", "invalid_audience"),
        ):
            response, _ = _request_rpc(
                client,
                token,
                {"jsonrpc": "2.0", "id": 3, "method": "tools/list", "params": {}},
            )
            assert response.status_code == 401
            assert response.json()["error"] == expected_error


def test_tools_list_requires_the_base_scope_and_exposes_schemas() -> None:
    with TestClient(create_app(_verify_test_token)) as client:
        response, _ = _request_rpc(
            client,
            "scopes:inventory:read",
            {"jsonrpc": "2.0", "id": 1, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 403
        assert response.json()["error"] == "missing_required_scopes"

        token = "scopes:trackflow:mcp+incidents:read+incidents:create+incidents:status:write+inventory:read"
        _initialize(client, token)
        response, payload = _request_rpc(
            client,
            token,
            {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        )
        assert response.status_code == 200
        tools = payload["result"]["tools"]
        by_name = {tool["name"]: tool for tool in tools}
        assert {
            "create_incident",
            "update_incident_status",
            "get_incident",
            "list_incidents",
            "search_inventory",
            "request_inventory_change",
        } <= by_name.keys()
        assert all(tool["description"] and tool["inputSchema"] for tool in tools)
        create_schema = by_name["create_incident"]["inputSchema"]
        assert create_schema["properties"]["title"]["maxLength"] == 160
        assert create_schema["properties"]["category"]["enum"] == [
            "Almacen",
            "Ultima_Milla",
            "Logistica_Inversa",
            "CX",
            "Comercial",
            "Tecnologia",
        ]


def test_inventory_write_tool_returns_explicit_read_only_error(caplog) -> None:
    token = "scopes:trackflow:mcp+inventory:read"
    caplog.set_level(logging.INFO, logger="trackflow_mcp.tools")
    with TestClient(create_app(_verify_test_token)) as client:
        _initialize(client, token)
        response, payload = _request_rpc(
            client,
            token,
            {
                "jsonrpc": "2.0",
                "id": 2,
                "method": "tools/call",
                "params": {
                    "name": "request_inventory_change",
                    "arguments": {
                        "operation": "inbound_order",
                        "sku_id": "sku-1",
                        "quantity": 5,
                    },
                },
            },
        )
        assert response.status_code == 200
        assert payload["result"]["isError"] is True
        assert "READ_ONLY" in payload["result"]["content"][0]["text"]
    assert "client=mcp-test-client tool=request_inventory_change result=error code=READ_ONLY" in caplog.text


def test_per_tool_scope_failure_is_logged_and_distinct(caplog) -> None:
    token = "scopes:trackflow:mcp"
    with caplog.at_level(logging.INFO, logger="trackflow_mcp.tools"):
        with TestClient(create_app(_verify_test_token)) as client:
            _initialize(client, token)
            response, payload = _request_rpc(
                client,
                token,
                {
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "get_incident",
                        "arguments": {"incident_id": "ticket-42"},
                    },
                },
            )
            assert response.status_code == 200
            assert payload["result"]["isError"] is True
            assert "INSUFFICIENT_SCOPE" in payload["result"]["content"][0]["text"]
    assert "client=mcp-test-client tool=get_incident result=error code=INSUFFICIENT_SCOPE" in caplog.text