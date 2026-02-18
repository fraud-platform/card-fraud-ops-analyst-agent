"""Insight schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from app.schemas.v1.common import ModelMode, Severity


class EvidenceItem(BaseModel):
    evidence_id: str
    evidence_kind: str
    evidence_payload: dict[str, Any]
    created_at: datetime


class InsightDetail(BaseModel):
    insight_id: str
    transaction_id: str
    severity: Severity
    summary: str
    insight_type: str
    model_mode: ModelMode
    generated_at: datetime
    evidence: list[EvidenceItem] = Field(default_factory=list)


class InsightListResponse(BaseModel):
    insights: list[InsightDetail]
    next_cursor: str | None = None
