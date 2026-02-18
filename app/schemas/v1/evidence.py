"""Evidence envelope schemas for structured evidence storage."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field


class EvidenceEnvelope(BaseModel):
    evidence_id: str
    evidence_kind: str
    category: str
    strength: float
    description: str
    supporting_data: dict[str, Any]
    timestamp: datetime
    freshness_weight: float
    related_transaction_ids: list[str] = Field(default_factory=list)
    evidence_references: dict[str, Any] = Field(default_factory=dict)


class EvidenceCreateRequest(BaseModel):
    evidence_kind: str
    category: str
    strength: float
    description: str
    supporting_data: dict[str, Any]
    related_transaction_ids: list[str] = Field(default_factory=list)
    evidence_references: dict[str, Any] = Field(default_factory=dict)
