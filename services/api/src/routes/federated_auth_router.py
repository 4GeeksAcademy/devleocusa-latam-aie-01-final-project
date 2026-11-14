"""Microsoft federated authentication routes; linking is session-protected."""

from __future__ import annotations

from urllib.parse import quote

from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import RedirectResponse
from pydantic import BaseModel

from src.models.federated_auth import FederatedIdentity
from src.models.user import User
from src.services.auth_service import create_access_token, get_current_user
from src.services.federated_auth_service import (
    FederatedAuthError,
    consume_login_code,
    consume_oauth_transaction,
    create_login_code,
    create_oauth_transaction,
    get_identity,
    get_linked_identities,
    link_identity,
    unlink_identity,
    write_audit_event,
)
from src.services.microsoft_oauth_service import (
    MicrosoftOAuthError,
    build_authorization_url,
    exchange_and_validate_identity,
    get_frontend_url,
    get_redirect_uri,
)

federated_auth_router = APIRouter(prefix="/auth/federated", tags=["federated-auth"])


class FederatedIdentityList(BaseModel):
    providers: list[FederatedIdentity]


class ExchangeCodeRequest(BaseModel):
    code: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class AuthorizationUrlResponse(BaseModel):
    authorization_url: str


def _start_oauth(purpose: str, user: User | None = None) -> RedirectResponse:
    try:
        transaction = create_oauth_transaction(purpose, user.id if user else None)
        return RedirectResponse(build_authorization_url(transaction), status_code=302)
    except (FederatedAuthError, MicrosoftOAuthError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@federated_auth_router.get("/providers", response_model=FederatedIdentityList)
def list_providers(current_user: User = Depends(get_current_user)) -> FederatedIdentityList:
    return FederatedIdentityList(providers=get_linked_identities(current_user.id))


@federated_auth_router.get("/microsoft/link")
def begin_link(current_user: User = Depends(get_current_user)) -> RedirectResponse:
    return _start_oauth("link", current_user)


@federated_auth_router.post("/microsoft/link/start", response_model=AuthorizationUrlResponse)
def start_link(current_user: User = Depends(get_current_user)) -> AuthorizationUrlResponse:
    """Create a link transaction from an authenticated browser API request."""
    try:
        transaction = create_oauth_transaction("link", current_user.id)
        return AuthorizationUrlResponse(authorization_url=build_authorization_url(transaction))
    except (FederatedAuthError, MicrosoftOAuthError) as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@federated_auth_router.get("/microsoft/login")
def begin_login() -> RedirectResponse:
    return _start_oauth("login")


@federated_auth_router.get("/microsoft/callback")
def microsoft_callback(
    code: str | None = None,
    state: str | None = None,
    error: str | None = None,
    redirect_uri: str | None = Query(default=None),
) -> RedirectResponse:
    """Validate state and fixed redirect URI, then execute link OR login flow."""
    frontend_url = get_frontend_url()
    if error or not code or not state:
        return RedirectResponse(f"{frontend_url}/login?federated_error=Microsoft+authentication+failed")
    try:
        configured_redirect = get_redirect_uri()
    except MicrosoftOAuthError as exc:
        return RedirectResponse(
            f"{frontend_url}/login?federated_error={quote(str(exc))}", status_code=303
        )
    if redirect_uri is not None and redirect_uri != configured_redirect:
        return RedirectResponse(
            f"{frontend_url}/login?federated_error=redirect_uri_mismatch", status_code=303
        )
    try:
        # The token exchange always uses the exact configured redirect URI; never
        # accept a callback override from query or body parameters.
        transaction = consume_oauth_transaction(state)
    except FederatedAuthError as exc:
        return RedirectResponse(
            f"{frontend_url}/login?federated_error={quote(str(exc))}"
        )

    try:
        identity = exchange_and_validate_identity(code, transaction)
        provider_user_id = identity["provider_user_id"]
        if transaction.purpose == "link":
            if transaction.user_id is None:
                raise FederatedAuthError("The authenticated user for this link was not found.")
            from src.services.user_service import get_user_by_id

            user = get_user_by_id(transaction.user_id)
            if user is None or not user.is_active:
                raise FederatedAuthError("The TrackFlow account is unavailable.")
            link_identity(user, provider_user_id, identity["email"])
            return RedirectResponse(f"{frontend_url}/account/user?federated=linked", status_code=303)

        linked = get_identity("microsoft", provider_user_id)
        if linked is None:
            write_audit_event("federated_login_rejected", provider_user_id, None)
            return RedirectResponse(
                f"{frontend_url}/login?federated_error=account_not_linked", status_code=303
            )
        from src.services.user_service import get_user_by_id

        user = get_user_by_id(linked.user_id)
        if user is None or not user.is_active:
            write_audit_event("federated_login_rejected", provider_user_id, linked.user_id)
            return RedirectResponse(
                f"{frontend_url}/login?federated_error=account_unavailable", status_code=303
            )
        write_audit_event("federated_login_success", provider_user_id, user.id)
        login_code = create_login_code(user.id)
        return RedirectResponse(
            f"{frontend_url}/login?federated_code={login_code}", status_code=303
        )
    except (MicrosoftOAuthError, FederatedAuthError) as exc:
        if transaction.purpose == "link":
            return RedirectResponse(
                f"{frontend_url}/account/user?federated_error={quote(str(exc))}",
                status_code=303,
            )
        return RedirectResponse(
            f"{frontend_url}/login?federated_error={quote(str(exc))}",
            status_code=303,
        )


@federated_auth_router.delete("/microsoft/link", status_code=status.HTTP_204_NO_CONTENT)
def remove_link(current_user: User = Depends(get_current_user)) -> None:
    try:
        unlink_identity(current_user, "microsoft")
    except FederatedAuthError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc)) from exc


@federated_auth_router.post("/exchange", response_model=TokenResponse)
def exchange_login_code(payload: ExchangeCodeRequest) -> TokenResponse:
    try:
        user = consume_login_code(payload.code)
    except FederatedAuthError as exc:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail=str(exc)) from exc
    return TokenResponse(access_token=create_access_token(user.id))
