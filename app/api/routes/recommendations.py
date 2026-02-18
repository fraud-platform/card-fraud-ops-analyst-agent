"""Recommendation routes."""

from fastapi import APIRouter, Depends, Query
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsAck, RequireOpsRead
from app.schemas.v1.common import Severity
from app.schemas.v1.recommendations import (
    AcknowledgeRequest,
    RecommendationDetail,
    RecommendationListResponse,
)
from app.services.recommendation_service import RecommendationService

router = APIRouter(prefix="/worklist", tags=["recommendations"])


@router.get("/recommendations", response_model=RecommendationListResponse)
async def list_recommendations(
    user: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
    limit: int = Query(50, ge=1, le=100),
    cursor: str | None = Query(None),
    severity: Severity | None = Query(None),
):
    """List recommendations in worklist with keyset pagination."""
    service = RecommendationService(session)
    recommendations, next_cursor = await service.list_worklist(
        limit=limit,
        cursor=cursor,
        severity=severity.value if severity else None,
    )
    return RecommendationListResponse(
        recommendations=recommendations,
        next_cursor=next_cursor,
        total=len(recommendations),
    )


@router.post(
    "/recommendations/{recommendation_id}/acknowledge", response_model=RecommendationDetail
)
async def acknowledge_recommendation(
    recommendation_id: str,
    request: AcknowledgeRequest,
    user: RequireOpsAck,
    session: AsyncSession = Depends(get_session),
):
    """Acknowledge or reject a recommendation."""
    service = RecommendationService(session)
    result = await service.acknowledge(
        recommendation_id=recommendation_id,
        user_id=user.user_id,
        action=request.action.value,
        comment=request.comment,
    )
    return result
