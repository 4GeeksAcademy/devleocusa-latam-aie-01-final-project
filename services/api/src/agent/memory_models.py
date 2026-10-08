from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from uuid import UUID

from pydantic import BaseModel, Field, field_validator, model_validator


class MemoryDecision(StrEnum):
    APPROVE = "approve"
    REJECT = "reject"
    EDIT = "edit"
    UNCERTAIN = "uncertain"


class MemoryCategory(StrEnum):
    CARRIER_RULE = "carrier_rule"
    RECURRING_INCIDENT = "recurring_incident"
    B2B_REPORT_PREFERENCE = "b2b_report_preference"


class MemoryProposal(BaseModel):
    category: MemoryCategory
    memory_key: str = Field(min_length=3, max_length=160)
    content: str = Field(min_length=5, max_length=500)
    reason: str = Field(min_length=3, max_length=300)
    country: str | None = Field(default=None, max_length=40)
    repetition_count: int | None = Field(default=None, ge=1, le=1000)

    @model_validator(mode="after")
    def validate_category_scope(self) -> "MemoryProposal":
        if self.category == MemoryCategory.CARRIER_RULE and not self.country:
            raise ValueError("Una regla de carrier debe tener ámbito país.")
        if self.category == MemoryCategory.RECURRING_INCIDENT and (self.repetition_count or 0) < 2:
            raise ValueError("Un incidente requiere al menos dos ocurrencias declaradas.")
        return self

    @field_validator("content", "reason")
    @classmethod
    def strip_text(cls, value: str) -> str:
        return value.strip()


class MemoryDecisionResult(BaseModel):
    decision: MemoryDecision
    explicit_confirmation: bool = False
    edited_content: str | None = Field(default=None, max_length=500)
    continuation: str = Field(default="", max_length=1000)

    @model_validator(mode="after")
    def approval_requires_confirmation(self) -> "MemoryDecisionResult":
        if self.decision == MemoryDecision.APPROVE and not self.explicit_confirmation:
            self.decision = MemoryDecision.REJECT
        if self.decision == MemoryDecision.UNCERTAIN:
            self.decision = MemoryDecision.REJECT
        return self


class MemoryProposalRecord(BaseModel):
    id: UUID
    user_id: str
    content: str
    category: MemoryCategory
    memory_key: str
    repetition_count: int | None = None
    source_message: str
    created_at: datetime


class MemoryRecord(BaseModel):
    id: UUID
    content: str
    category: MemoryCategory
    memory_key: str
    approved_at: datetime
    expires_at: datetime | None = None