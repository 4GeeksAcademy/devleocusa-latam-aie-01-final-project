from __future__ import annotations

import logging

import jwt
from mcpauth import MCPAuth
from mcpauth.config import (
    AuthServerConfig,
    AuthServerType,
    AuthorizationServerMetadata,
)
from mcpauth.exceptions import MCPAuthTokenVerificationException
from mcpauth.utils import create_verify_jwt
from pydantic import ValidationError

from trackflow_mcp.settings import settings


logger = logging.getLogger("trackflow_mcp.auth")

MCP_SCOPES = [
    "openid",
    settings.mcp_required_scope,
    "incidents:read",
    "incidents:create",
    "incidents:status:write",
    "inventory:read",
]

authorization_server = AuthorizationServerMetadata(
    issuer=settings.issuer,
    authorization_endpoint=settings.authorization_endpoint,
    token_endpoint=settings.token_endpoint,
    jwks_uri=settings.jwks_uri,
    response_types_supported=["code"],
    grant_types_supported=["authorization_code", "client_credentials"],
    scope_supported=MCP_SCOPES,
    code_challenge_methods_supported=["S256"],
)

mcp_auth = MCPAuth(
    server=AuthServerConfig(
        metadata=authorization_server,
        type=AuthServerType.OIDC,
    )
)

_verify_jwt = create_verify_jwt(settings.jwks_uri)


def verify_access_token(token: str):
    try:
        return _verify_jwt(token)
    except MCPAuthTokenVerificationException as error:
        cause = error.cause
        cause_type = type(cause).__name__ if cause is not None else "unknown"
        token_algorithm = "unknown"
        token_key_id = "unknown"
        claim_names: list[str] = []

        try:
            token_header = jwt.get_unverified_header(token)
            token_algorithm = str(token_header.get("alg", "unknown"))
            token_key_id = str(token_header.get("kid", "unknown"))
            token_payload = jwt.decode(
                token,
                options={"verify_signature": False, "verify_exp": False},
                algorithms=[token_algorithm],
            )
            claim_names = sorted(token_payload.keys())
        except (jwt.PyJWTError, TypeError, ValueError):
            pass

        failed_fields: list[str] = []
        if isinstance(cause, ValidationError):
            failed_fields = sorted(
                {
                    ".".join(str(part) for part in issue.get("loc", ()))
                    for issue in cause.errors()
                }
            )

        logger.warning(
            "access_token_rejected code=%s cause=%s alg=%s kid=%s claims=%s failed_fields=%s",
            error.code,
            cause_type,
            token_algorithm,
            token_key_id,
            claim_names,
            failed_fields,
        )
        raise


def protected_resource_metadata() -> dict[str, object]:
    return {
        "resource": settings.mcp_resource_url,
        "authorization_servers": [settings.issuer],
        "scopes_supported": MCP_SCOPES,
        "bearer_methods_supported": ["header"],
    }