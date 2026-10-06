from __future__ import annotations

import asyncio

import httpx

from src.agent.mcp_tools import OAuthClientCredentials


def test_client_credentials_auth_fetches_and_caches_bearer(monkeypatch) -> None:
    monkeypatch.setenv("MCP_OAUTH_TOKEN_URL", "https://issuer.test/token")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_ID", "trackflow-agent")
    monkeypatch.setenv("MCP_OAUTH_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("MCP_OAUTH_SCOPES", "trackflow:mcp incidents:read")
    token_requests: list[httpx.Request] = []
    resource_requests: list[httpx.Request] = []

    def token_handler(request: httpx.Request) -> httpx.Response:
        token_requests.append(request)
        assert request.method == "POST"
        assert request.url == "https://issuer.test/token"
        assert b"grant_type=client_credentials" in request.content
        assert b"scope=trackflow%3Amcp+incidents%3Aread" in request.content
        return httpx.Response(200, json={"access_token": "oauth-test-token", "expires_in": 300})

    def resource_handler(request: httpx.Request) -> httpx.Response:
        resource_requests.append(request)
        return httpx.Response(200, json={"ok": True})

    auth = OAuthClientCredentials(token_transport=httpx.MockTransport(token_handler))

    async def call_twice() -> None:
        async with httpx.AsyncClient(
            base_url="https://mcp.test",
            transport=httpx.MockTransport(resource_handler),
            auth=auth,
        ) as client:
            await client.get("/first")
            await client.get("/second")

    asyncio.run(call_twice())

    assert len(token_requests) == 1
    assert len(resource_requests) == 2
    assert all(
        request.headers["Authorization"] == "Bearer oauth-test-token"
        for request in resource_requests
    )