"""User models and enums for authentication data persisted in TinyDB."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum

from pydantic import BaseModel, Field

TinyDBId = int | str


class UserRole(str, Enum):
    """Human roles; ``user``/``manager`` are retained as wire-compatible values."""

    ADMIN = "admin"
    MANAGER = "manager"
    USER = "user"
    SERVICE = "service"

    @property
    def display_name(self) -> str:
        return {
            UserRole.ADMIN: "Admin",
            UserRole.MANAGER: "Supervisor",
            UserRole.USER: "Empleado",
            UserRole.SERVICE: "Servicio técnico",
        }[self]


class Department(str, Enum):
    """TrackFlow organizational departments; independent from the user's role."""

    WAREHOUSE_OPERATIONS = "Operaciones de Almacén"
    LAST_MILE_CARRIERS = "Última Milla y Gestión de Carriers"
    RETURNS = "Logística Inversa (Devoluciones)"
    CUSTOMER_EXPERIENCE = "Experiencia del Cliente (CX)"
    COMMERCIAL = "Comercial y Relación con Clientes"
    PEOPLE = "Personas"
    TECHNOLOGY = "Tecnología"
    EXECUTIVE = "Dirección Ejecutiva"


class User(BaseModel):
    """User record model stored in TinyDB."""

    id: TinyDBId
    email: str = Field(min_length=3)
    hashed_password: str = Field(min_length=1)
    is_active: bool = True
    role: UserRole
    # Missing department is unassigned and fails closed for scoped resources.
    department: Department | None = None
    # Provisioned by an administrator; never accepted by public registration.
    # None is intentionally treated as unassigned and fails closed on tenant APIs.
    tenant_id: str | None = None
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
