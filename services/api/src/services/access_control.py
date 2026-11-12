"""Authorization policies for internal and service identities."""

from __future__ import annotations

from collections.abc import Iterable

from fastapi import Depends, HTTPException, status

from src.models.user import Department, User, UserRole
from src.services.auth_service import get_current_user


ROLE_LEVEL: dict[UserRole, int] = {
    UserRole.USER: 1,
    UserRole.MANAGER: 2,
    UserRole.ADMIN: 3,
}


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def require_role(minimum_role: UserRole):
    """Build a centralized dependency enforcing the human role hierarchy."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.SERVICE or ROLE_LEVEL.get(current_user.role, 0) < ROLE_LEVEL[minimum_role]:
            raise _forbidden(f"Se requiere el rol {minimum_role.display_name} o superior.")
        return current_user

    return dependency


def require_roles(allowed_roles: Iterable[UserRole]):
    """Build a centralized dependency for an explicit set of roles."""
    allowed = frozenset(allowed_roles)

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role not in allowed:
            raise _forbidden("El rol del usuario no permite esta operación.")
        return current_user

    return dependency


def require_department(department: Department, *, admin_global: bool = True):
    """Require data ownership scope independently of role capabilities."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if admin_global and current_user.role == UserRole.ADMIN:
            return current_user
        if current_user.department != department:
            raise _forbidden("El departamento del usuario no tiene acceso a estos datos.")
        return current_user

    return dependency


def require_access(minimum_role: UserRole, department: Department):
    """Require both a capability level and the resource's department scope."""

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.SERVICE or ROLE_LEVEL.get(current_user.role, 0) < ROLE_LEVEL[minimum_role]:
            raise _forbidden(f"Se requiere el rol {minimum_role.display_name} o superior.")
        if current_user.role != UserRole.ADMIN and current_user.department != department:
            raise _forbidden("El departamento del usuario no tiene acceso a estos datos.")
        return current_user

    return dependency


def require_internal_operator(
    current_user: User = Depends(get_current_user),
) -> User:
    """Allow only TrackFlow operators; end-customer accounts fail closed."""
    if current_user.role not in {UserRole.ADMIN, UserRole.MANAGER, UserRole.USER}:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Acceso reservado a personal autorizado de TrackFlow.",
        )
    return current_user


def require_employee_self_or_people(target_user_id: str):
    """Allow People department access or an employee to their own HR record.

    Admin has global access. Supervisors outside People are deliberately not
    allowed to inspect contracts, justified absences, or personal data.
    """

    def dependency(current_user: User = Depends(get_current_user)) -> User:
        if current_user.role == UserRole.ADMIN:
            return current_user
        if (
            current_user.role in {UserRole.USER, UserRole.MANAGER}
            and current_user.department == Department.PEOPLE
        ):
            return current_user
        if current_user.role == UserRole.USER and str(current_user.id) == target_user_id:
            return current_user
        raise _forbidden("El departamento o rol del usuario no permite acceder a estos datos.")

    return dependency


def ensure_employee_self_or_people(current_user: User, target_user_id: str) -> User:
    """Enforce the People-data policy for a route with a dynamic target ID."""
    if current_user.role == UserRole.ADMIN or (
        current_user.role in {UserRole.USER, UserRole.MANAGER}
        and current_user.department == Department.PEOPLE
    ):
        return current_user
    if current_user.role == UserRole.USER and str(current_user.id) == target_user_id:
        return current_user
    raise _forbidden("El departamento o rol del usuario no permite acceder a estos datos.")


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