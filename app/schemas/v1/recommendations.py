"""Recommendation schemas."""

from datetime import datetime
from typing import Any

from pydantic import BaseModel

from app.schemas.v1.common import RecommendationStatus, RecommendationType


class AcknowledgeRequest(BaseModel):
    action: RecommendationStatus
    comment: str | None = None


class RecommendationListResponse(BaseModel):
    recommendations: list[RecommendationDetail]
    next_cursor: str | None = None
    total: int = 0


class RecommendationDetail(BaseModel):
    recommendation_id: str
    insight_id: str
    type: RecommendationType
    status: RecommendationStatus
    priority: int = 0
    payload: dict[str, Any]
    acknowledged_by: str | None = None
    acknowledged_at: datetime | None = None
    created_at: datetime
