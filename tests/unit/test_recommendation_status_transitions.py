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
