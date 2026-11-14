"""Models for explicitly linked federated identities and OAuth state."""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

FederatedProvider = Literal["microsoft"]
UserAudience = Literal["internal", "b2b_client"]


class FederatedIdentity(BaseModel):
    """Provider identity deliberately linked to one existing TrackFlow user."""

    model_config = ConfigDict(extra="forbid")

    user_id: int | str
    provider: FederatedProvider = "microsoft"
    provider_user_id: str = Field(min_length=1)
    email_at_link_time: str = Field(min_length=1)
    linked_at: datetime
    audience: UserAudience


class FederatedAuditEvent(BaseModel):
    """Auditable federated-auth event; user_id is null for unknown login attempts."""

    event: Literal[
        "federated_link",
        "federated_unlink",
        "federated_login_success",
        "federated_login_rejected",
    ]
    timestamp: datetime
    user_id: int | str | None = None
    provider: FederatedProvider = "microsoft"
    provider_user_id: str


class OAuthTransaction(BaseModel):
    """Short-lived, single-use OAuth transaction; contains no provider tokens."""

    state: str
    purpose: Literal["link", "login"]
    user_id: int | str | None = None
    nonce: str
    code_verifier: str
    expires_at: datetime
    consumed: bool = False


class FederatedLoginCode(BaseModel):
    """Short-lived one-time code exchanged for a TrackFlow JWT."""

    code: str
    user_id: int | str
    expires_at: datetime
    consumed: bool = False
