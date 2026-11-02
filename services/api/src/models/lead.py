"""Schemas for public lead intake and internal CRM operations."""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, field_validator


class LeadStatus(str, Enum):
    NEW = "new"
    CONTACTED = "contacted"
    QUALIFIED = "qualified"
    DISQUALIFIED = "disqualified"


class LeadFields(BaseModel):
    """Canonical validated business data. JSON aliases match the web form."""

    model_config = ConfigDict(
        alias_generator=lambda name: name.split("_")[0] + "".join(part.title() for part in name.split("_")[1:]),
        populate_by_name=True,
        extra="forbid",
    )

    company_name: str = Field(min_length=2, max_length=160)
    contact_person: str = Field(min_length=3, max_length=160)
    corporate_email: str = Field(min_length=5, max_length=254)
    phone: str = Field(min_length=5, max_length=40)
    website: HttpUrl | None = None
    country_operation: str = Field(min_length=1, max_length=40)
    product_type: str = Field(min_length=1, max_length=40)
    monthly_volume: str = Field(min_length=1, max_length=40)
    services: list[str] = Field(min_length=1, max_length=3)
    other_3pl: str = Field(alias="other3pl", min_length=1, max_length=40)
    comments: str = Field(default="", max_length=500)
    privacy_policy: bool

    @field_validator("company_name", "contact_person", "phone", "country_operation", "product_type", "monthly_volume", "other_3pl", mode="before")
    @classmethod
    def strip_text(cls, value: object) -> object:
        return value.strip() if isinstance(value, str) else value

    @field_validator("corporate_email")
    @classmethod
    def validate_corporate_email(cls, value: str) -> str:
        value = value.strip()
        import re

        if not re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", value):
            raise ValueError("Email corporativo no válido")
        return value

    @field_validator("phone")
    @classmethod
    def validate_phone_country_code(cls, value: str) -> str:
        import re

        if not re.fullmatch(r"\+\d{1,3}\s.+", value):
            raise ValueError("El teléfono debe incluir código de país")
        return value

    @field_validator("website", mode="before")
    @classmethod
    def normalize_optional_website(cls, value: object) -> object:
        return None if value == "" else value

    @field_validator("country_operation")
    @classmethod
    def validate_country(cls, value: str) -> str:
        if value not in {"Estados Unidos", "España", "Ambos", "Otro"}:
            raise ValueError("País de operación no válido")
        return value

    @field_validator("product_type")
    @classmethod
    def validate_product_type(cls, value: str) -> str:
        if value not in {"Moda", "Electrónica", "Cosmética", "Alimentación", "Otro"}:
            raise ValueError("Tipo de producto no válido")
        return value

    @field_validator("monthly_volume")
    @classmethod
    def validate_monthly_volume(cls, value: str) -> str:
        if value not in {"0-100", "101-500", "501-2000", "2000+", "No estoy seguro"}:
            raise ValueError("Volumen mensual no válido")
        return value

    @field_validator("services")
    @classmethod
    def validate_services(cls, value: list[str]) -> list[str]:
        allowed = {"Almacenaje", "Última milla", "Logística inversa"}
        if not value or len(value) != len(set(value)) or any(service not in allowed for service in value):
            raise ValueError("Selecciona servicios de interés válidos")
        return value

    @field_validator("other_3pl")
    @classmethod
    def validate_other_3pl(cls, value: str) -> str:
        if value not in {"Sí", "No", "Estoy evaluando opciones"}:
            raise ValueError("La opción logística no es válida")
        return value

    @field_validator("privacy_policy")
    @classmethod
    def require_privacy_policy(cls, value: bool) -> bool:
        if value is not True:
            raise ValueError("Es necesario aceptar la política de privacidad")
        return value

    @field_validator("contact_person")
    @classmethod
    def require_full_name(cls, value: str) -> str:
        if len(value.split()) < 2:
            raise ValueError("Ingresa nombre y apellido del contacto")
        return value


class LeadCreate(LeadFields):
    pass


class LeadUpdate(LeadFields):
    pass


class LeadResponse(LeadFields):
    id: UUID
    status: LeadStatus
    created_at: datetime
    updated_at: datetime


class LeadStatusUpdate(BaseModel):
    status: LeadStatus


def utc_now() -> datetime:
    return datetime.now(timezone.utc)