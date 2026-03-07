"""Unit tests for recommendation status transition guards."""

from unittest.mock import AsyncMock

import pytest

from app.core.errors import ConflictError
from app.services.recommendation_service import RecommendationService


@pytest.mark.asyncio
async def test_acknowledge_allows_open_to_acknowledged():
    service = RecommendationService(AsyncMock())
    service.recommendation_repo.get = AsyncMock(return_value={"status": "OPEN"})
    service.recommendation_repo.update_status_with_guard = AsyncMock(
        return_value={"recommendation_id": "r1", "status": "ACKNOWLEDGED"}
    )
    service.audit_repo.emit = AsyncMock()

    result = await service.acknowledge("r1", "u1", "ACKNOWLEDGED")

    assert result["status"] == "ACKNOWLEDGED"


@pytest.mark.asyncio
async def test_acknowledge_rejects_invalid_transition():
    service = RecommendationService(AsyncMock())
    service.recommendation_repo.get = AsyncMock(return_value={"status": "EXPORTED"})

    with pytest.raises(ConflictError):
        await service.acknowledge("r1", "u1", "REJECTED")


@pytest.mark.asyncio
async def test_list_worklist_normalizes_legacy_recommendation_types():
    service = RecommendationService(AsyncMock())
    service.recommendation_repo.list_open = AsyncMock(
        return_value=(
            [
                {"type": "REVIEW", "status": "OPEN", "title": "A"},
                {"type": "case_action", "status": "OPEN", "title": "B"},
                {"type": "RULE_CANDIDATE", "status": "OPEN", "title": "C"},
            ],
            "cursor-1",
        )
    )

    recommendations, cursor = await service.list_worklist(limit=3)

    assert cursor == "cursor-1"
    assert recommendations[0]["type"] == "review_priority"
    assert recommendations[1]["type"] == "case_action"
    assert recommendations[2]["type"] == "rule_candidate"
