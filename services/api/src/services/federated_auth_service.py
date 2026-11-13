"""Storage and audit operations for explicitly linked Microsoft identities."""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from functools import wraps
from threading import RLock
from typing import Callable, TypeVar

from tinydb import Query

from src.database import (
    get_federated_audit_table,
    get_federated_identities_table,
    get_federated_login_codes_table,
    get_oauth_transactions_table,
)
from src.models.federated_auth import FederatedIdentity, OAuthTransaction
from src.models.user import TinyDBId, User
from src.services.user_service import get_user_by_id


class FederatedAuthError(ValueError):
    """Expected business-rule error in federated authentication."""


_operation_lock = RLock()
_T = TypeVar("_T")


def _serialized(operation: Callable[..., _T]) -> Callable[..., _T]:
    """Serialize read-check-write security operations within this process."""
    @wraps(operation)
    def wrapped(*args, **kwargs):
        with _operation_lock:
            return operation(*args, **kwargs)

    return wrapped


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _id_query(provider: str, provider_user_id: str):
    query = Query()
    return (query.provider == provider) & (query.provider_user_id == provider_user_id)


def get_linked_identities(user_id: TinyDBId) -> list[FederatedIdentity]:
    query = Query()
    return [
        FederatedIdentity.model_validate(record)
        for record in get_federated_identities_table().search(query.user_id == user_id)
    ]


def get_identity(provider: str, provider_user_id: str) -> FederatedIdentity | None:
    record = get_federated_identities_table().get(_id_query(provider, provider_user_id))
    return FederatedIdentity.model_validate(record) if record else None


def write_audit_event(
    event: str,
    provider_user_id: str,
    user_id: TinyDBId | None = None,
    provider: str = "microsoft",
) -> None:
    get_federated_audit_table().insert(
        {
            "event": event,
            "timestamp": _now().isoformat(),
            "user_id": user_id,
            "provider": provider,
            "provider_user_id": provider_user_id,
        }
    )


def seed_federated_auth_users() -> list[User]:
    """Idempotently create the briefing's demo users and explicit Microsoft link."""
    from src.services.user_service import create_user, get_user_by_email

    users = [
        {
            "email": "miguel.commercial@trackflow.example",
            "name": "Miguel Torres",
            "audience": "internal",
            "linked_provider_user_id": "ms-oid-miguel-001",
        },
        {
            "email": "brand.am@northwind.example",
            "name": "Northwind Account Manager",
            "audience": "b2b_client",
            "linked_provider_user_id": None,
        },
    ]
    result: list[User] = []
    for seed in users:
        user = get_user_by_email(seed["email"])
        if user is None:
            user = create_user(
                email=seed["email"],
                password=secrets.token_urlsafe(32),
                name=seed["name"],
                audience=seed["audience"],
            )
        provider_user_id = seed["linked_provider_user_id"]
        if provider_user_id and get_identity("microsoft", provider_user_id) is None:
            link_identity(user, provider_user_id, user.email)
        result.append(user)
    return result


@_serialized
def link_identity(
    user: User,
    provider_user_id: str,
    email_at_link_time: str,
) -> FederatedIdentity:
    if not provider_user_id.strip():
        raise FederatedAuthError("Microsoft did not return a valid identity identifier.")
    existing = get_identity("microsoft", provider_user_id)
    if existing is not None:
        if str(existing.user_id) == str(user.id):
            raise FederatedAuthError("This Microsoft account is already linked to your TrackFlow account.")
        raise FederatedAuthError("This Microsoft account is already linked to another TrackFlow account.")

    # TinyDB's table operations are process-thread locked. Production deployments
    # with multiple workers should use a transactional store with a unique index.
    identity = FederatedIdentity(
        user_id=user.id,
        provider="microsoft",
        provider_user_id=provider_user_id,
        email_at_link_time=email_at_link_time,
        linked_at=_now(),
        audience=user.audience,  # server-managed user classification; never trust IdP claims
    )
    get_federated_identities_table().insert(identity.model_dump(mode="json"))
    write_audit_event("federated_link", provider_user_id, user.id)
    return identity


def unlink_identity(user: User, provider: str) -> None:
    if provider != "microsoft":
        raise FederatedAuthError("Only Microsoft identities are supported.")
    links = get_linked_identities(user.id)
    target = next((link for link in links if link.provider == provider), None)
    if target is None:
        raise FederatedAuthError("No Microsoft account is linked to this TrackFlow account.")
    if not user.hashed_password.strip():
        raise FederatedAuthError("Add a password or another approved sign-in method before unlinking Microsoft.")
    get_federated_identities_table().remove(_id_query(provider, target.provider_user_id))
    write_audit_event("federated_unlink", target.provider_user_id, user.id)


def create_oauth_transaction(
    purpose: str,
    user_id: TinyDBId | None = None,
    lifetime_seconds: int = 600,
) -> OAuthTransaction:
    if purpose not in {"link", "login"}:
        raise FederatedAuthError("Invalid OAuth transaction purpose.")
    if purpose == "link" and user_id is None:
        raise FederatedAuthError("An authenticated user is required to link Microsoft.")
    if purpose == "link":
        user = get_user_by_id(user_id)
        if user is None or not user.is_active:
            raise FederatedAuthError("The TrackFlow account is unavailable.")
    transaction = OAuthTransaction(
        state=secrets.token_urlsafe(32),
        purpose=purpose,  # type: ignore[arg-type]
        user_id=user_id,
        nonce=secrets.token_urlsafe(32),
        code_verifier=secrets.token_urlsafe(48),
        expires_at=_now() + timedelta(seconds=lifetime_seconds),
    )
    get_oauth_transactions_table().insert(transaction.model_dump(mode="json"))
    return transaction


@_serialized
def consume_oauth_transaction(state: str, purpose: str | None = None) -> OAuthTransaction:
    """Validate and consume one OAuth state exactly once.

    ``purpose`` is checked before marking the transaction consumed. Callers handling
    a callback should first retrieve it by state, then use its persisted purpose.
    """
    table = get_oauth_transactions_table()
    query = Query()
    record = table.get(query.state == state)
    if record is None or record.get("consumed"):
        raise FederatedAuthError("OAuth state is invalid, expired, or already used.")
    transaction = OAuthTransaction.model_validate(record)
    if purpose is not None and transaction.purpose != purpose:
        raise FederatedAuthError("OAuth transaction purpose does not match.")
    if transaction.expires_at <= _now():
        table.remove(doc_ids=[record.doc_id])
        raise FederatedAuthError("OAuth state is invalid, expired, or already used.")
    table.update({"consumed": True}, doc_ids=[record.doc_id])
    return transaction


def create_login_code(user_id: TinyDBId, lifetime_seconds: int = 60) -> str:
    code = secrets.token_urlsafe(32)
    get_federated_login_codes_table().insert(
        {
            "code": code,
            "user_id": user_id,
            "expires_at": (_now() + timedelta(seconds=lifetime_seconds)).isoformat(),
            "consumed": False,
        }
    )
    return code


@_serialized
def consume_login_code(code: str) -> User:
    table = get_federated_login_codes_table()
    query = Query()
    record = table.get(query.code == code)
    if record is None or record.get("consumed"):
        raise FederatedAuthError("Login code is invalid, expired, or already used.")
    expires_at = datetime.fromisoformat(record["expires_at"])
    if expires_at <= _now():
        table.remove(doc_ids=[record.doc_id])
        raise FederatedAuthError("Login code is invalid, expired, or already used.")
    table.update({"consumed": True}, doc_ids=[record.doc_id])
    user = get_user_by_id(record["user_id"])
    if user is None or not user.is_active:
        raise FederatedAuthError("TrackFlow account is unavailable.")
    return user
