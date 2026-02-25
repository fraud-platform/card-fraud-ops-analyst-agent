"""Insights routes for agentic API."""

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.database import get_session
from app.core.dependencies import RequireOpsRead
from app.persistence.insight_repository import InsightRepository
from app.schemas.v1.insights import InsightListResponse

router = APIRouter(prefix="/transactions", tags=["insights"])


@router.get("/{transaction_id}/insights", response_model=InsightListResponse)
async def get_transaction_insights(
    transaction_id: str,
    _auth: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    """Get all insights for a transaction with evidence."""
    repo = InsightRepository(session)
    insights = await repo.get_insights_with_evidence(transaction_id)
    return InsightListResponse(insights=insights)
