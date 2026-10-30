"""Authorization policies for internal and service identities."""

from __future__ import annotations

from fastapi import Depends, HTTPException, status

from src.models.user import User, UserRole
from src.services.auth_service import get_current_user


def require_internal_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow only TrackFlow operators; end-customer accounts fail closed."""
    if current_user.role not in {UserRole.ADMIN, UserRole.MANAGER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso reservado a personal autorizado de TrackFlow.",
        )
    return current_user


def require_service_or_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow operators and the explicitly provisioned MCP service identity."""
    if current_user.role not in {
        UserRole.ADMIN,
        UserRole.MANAGER,
        UserRole.SERVICE,
    }:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso reservado a personal o servicios autorizados.",
        )
    return current_user


def require_incident_writer(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow operator mutations or the dedicated MCP service identity.

    MCP OAuth scopes still gate which mutation tool can be called. This API
    identity is a trusted service credential, not an end-user identity.
    """
    if current_user.role not in {UserRole.ADMIN, UserRole.MANAGER, UserRole.SERVICE}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Operación reservada a personal autorizado de TrackFlow.",
        )
    return current_user