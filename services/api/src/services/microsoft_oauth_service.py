"""Microsoft OAuth 2.0 / OIDC integration. Provider tokens are never persisted."""

from __future__ import annotations

import base64
import hashlib
import os
from typing import Any
from urllib.parse import urlencode

import httpx
from jose import JWTError, jwt
from urllib.parse import urlparse

from src.models.federated_auth import OAuthTransaction

MICROSOFT_AUTHORITY = "https://login.microsoftonline.com"


class MicrosoftOAuthError(ValueError):
    """Microsoft configuration, transport, or identity validation failure."""


def _required_env(name: str) -> str:
    value = os.getenv(name, "").strip()
    if not value:
        raise MicrosoftOAuthError(f"Missing required OAuth configuration: {name}.")
    return value


def get_client_id() -> str:
    return _required_env("MICROSOFT_CLIENT_ID")


def get_client_secret() -> str:
    return _required_env("MICROSOFT_CLIENT_SECRET")


def get_tenant_id() -> str:
    # `organizations` enables corporate M365 users. The TrackFlow user must still exist.
    return _required_env("MICROSOFT_TENANT_ID")


def get_redirect_uri() -> str:
    configured = _required_env("OAUTH_REDIRECT_URI")
    parsed = urlparse(configured)
    if parsed.scheme != "https" and not (
        parsed.scheme == "http" and parsed.hostname in {"localhost", "127.0.0.1"}
    ):
        raise MicrosoftOAuthError("OAUTH_REDIRECT_URI must use HTTPS except for local development.")
    if not parsed.netloc or parsed.username or parsed.password or parsed.fragment:
        raise MicrosoftOAuthError("OAUTH_REDIRECT_URI is malformed.")
    return configured


def get_frontend_url() -> str:
    value = os.getenv("FEDERATED_AUTH_FRONTEND_URL", "http://localhost:3000").strip().rstrip("/")
    if not value.startswith(("https://", "http://localhost")):
        raise MicrosoftOAuthError("FEDERATED_AUTH_FRONTEND_URL must use HTTPS except for local development.")
    return value


def build_authorization_url(transaction: OAuthTransaction) -> str:
    client_id = get_client_id()
    tenant = get_tenant_id()
    redirect_uri = get_redirect_uri()
    verifier = transaction.code_verifier.encode("ascii")
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier).digest()).rstrip(b"=").decode("ascii")
    params = {
        "client_id": client_id,
        "response_type": "code",
        "redirect_uri": redirect_uri,
        "response_mode": "query",
        "scope": "openid profile email",
        "state": transaction.state,
        "nonce": transaction.nonce,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
    }
    return f"{MICROSOFT_AUTHORITY}/{tenant}/oauth2/v2.0/authorize?{urlencode(params)}"


def exchange_and_validate_identity(code: str, transaction: OAuthTransaction) -> dict[str, str]:
    """Exchange an authorization code and validate the signed ID token."""
    tenant = get_tenant_id()
    token_url = f"{MICROSOFT_AUTHORITY}/{tenant}/oauth2/v2.0/token"
    form = {
        "client_id": get_client_id(),
        "client_secret": get_client_secret(),
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": get_redirect_uri(),
        "code_verifier": transaction.code_verifier,
        "scope": "openid profile email",
    }
    try:
        response = httpx.post(token_url, data=form, timeout=10.0)
        response.raise_for_status()
        token_payload = response.json()
        raw_id_token = token_payload.get("id_token")
        if not isinstance(raw_id_token, str):
            raise MicrosoftOAuthError("Microsoft did not return an OIDC identity token.")

        unverified = jwt.get_unverified_header(raw_id_token)
        key_id = unverified.get("kid")
        jwks_url = f"{MICROSOFT_AUTHORITY}/{tenant}/discovery/v2.0/keys"
        keys_response = httpx.get(jwks_url, timeout=10.0)
        keys_response.raise_for_status()
        keys = keys_response.json().get("keys", [])
        signing_key: dict[str, Any] | None = next(
            (key for key in keys if key.get("kid") == key_id), None
        )
        if signing_key is None:
            raise MicrosoftOAuthError("Microsoft signing key was not found.")

        claims = jwt.decode(
            raw_id_token,
            signing_key,
            algorithms=["RS256"],
            audience=get_client_id(),
            options={"verify_iss": False},
        )
    except MicrosoftOAuthError:
        raise
    except (httpx.HTTPError, ValueError, KeyError, TypeError, JWTError) as exc:
        raise MicrosoftOAuthError("Microsoft authentication could not be validated.") from exc

    issuer = str(claims.get("iss", ""))
    tenant_claim = str(claims.get("tid", ""))
    expected_issuer = f"{MICROSOFT_AUTHORITY}/{tenant_claim}/v2.0"
    if not tenant_claim or issuer != expected_issuer:
        raise MicrosoftOAuthError("Microsoft issuer is invalid.")
    if claims.get("nonce") != transaction.nonce:
        raise MicrosoftOAuthError("Microsoft nonce validation failed.")
    if tenant not in {"common", "organizations", "consumers"} and tenant_claim.lower() != tenant.lower():
        raise MicrosoftOAuthError("Microsoft tenant is not allowed.")

    provider_user_id = claims.get("oid") or claims.get("sub")
    email = claims.get("preferred_username") or claims.get("email")
    if not isinstance(provider_user_id, str) or not provider_user_id:
        raise MicrosoftOAuthError("Microsoft identity is missing a stable user identifier.")
    if not isinstance(email, str) or not email:
        email = "unknown@microsoft.invalid"
    return {"provider_user_id": provider_user_id, "email": email}
