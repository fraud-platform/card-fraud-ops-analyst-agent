"""Insight routes."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsRead
from app.schemas.v1.insights import InsightListResponse
from app.services.insight_service import InsightService

router = APIRouter(prefix="/transactions", tags=["insights"])


@router.get("/{transaction_id}/insights", response_model=InsightListResponse)
async def get_transaction_insights(
    transaction_id: str,
    user: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get latest insight snapshots for a transaction."""
    service = InsightService(session)
    insights = await service.get_insights_for_transaction(transaction_id)
    return InsightListResponse(insights=insights)
