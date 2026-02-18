"""Unit tests for insight service."""

import json
from unittest.mock import AsyncMock

import pytest

from app.services.insight_service import InsightService


@pytest.mark.asyncio
async def test_get_insights_for_transaction():
    """Test getting insights for a transaction."""
    mock_session = AsyncMock()
    service = InsightService(mock_session)

    mock_insights = [
        {
            "insight_id": "insight-1",
            "transaction_id": "txn-123",
            "evidence": [{"type": "pattern", "summary": "Burst activity"}],
        },
        {
            "insight_id": "insight-2",
            "transaction_id": "txn-123",
            "evidence": [{"type": "similarity", "summary": "Similar transaction"}],
        },
    ]

    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=mock_insights)

    result = await service.get_insights_for_transaction("txn-123")

    print("\n[INSIGHT_SERVICE] Input transaction_id: txn-123")
    print(f"[INSIGHT_SERVICE] Output insights count: {len(result)}")
    print(f"[INSIGHT_SERVICE] Response JSON:\n{json.dumps(result, indent=2, default=str)}")

    assert len(result) == 2
    assert result[0]["insight_id"] == "insight-1"
    assert result[0]["transaction_id"] == "txn-123"
    assert len(result[0]["evidence"]) == 1
    service.insight_repo.get_insights_with_evidence.assert_called_once_with("txn-123")


@pytest.mark.asyncio
async def test_get_insights_for_transaction_empty():
    """Test getting insights when none exist."""
    mock_session = AsyncMock()
    service = InsightService(mock_session)

    service.insight_repo.get_insights_with_evidence = AsyncMock(return_value=[])

    result = await service.get_insights_for_transaction("txn-999")

    print("\n[INSIGHT_SERVICE] Input transaction_id: txn-999")
    print(f"[INSIGHT_SERVICE] Output insights count: {len(result)}")
    print(f"[INSIGHT_SERVICE] Response JSON:\n{json.dumps(result, indent=2, default=str)}")

    assert len(result) == 0
    assert result == []
