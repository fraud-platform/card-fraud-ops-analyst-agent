"""Insight service - read insight snapshots."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.insight_repository import InsightRepository


class InsightService:
    """Service for reading insights."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.insight_repo = InsightRepository(session)

    async def get_insights_for_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get all insights for a transaction."""
        insights = await self.insight_repo.get_insights_with_evidence(transaction_id)
        return insights
