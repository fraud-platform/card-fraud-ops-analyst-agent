"""Unit tests for rule draft engine."""

from unittest.mock import MagicMock

import pytest

from app.agents.rule_draft_engine import RuleDraftEngine
from app.core.errors import ConflictError, ValidationError


@pytest.mark.asyncio
async def test_rule_draft_engine_validates_recommendation_type():
    mock_session = MagicMock()
    engine = RuleDraftEngine(mock_session)

    recommendation = {
        "recommendation_id": "rec-123",
        "type": "review_priority",
        "status": "ACKNOWLEDGED",
    }
    insight = {"insight_id": "ins-123"}
    evidence = []

    with pytest.raises(ValidationError) as exc_info:
        await engine.create_draft(
            recommendation=recommendation,
            insight=insight,
            evidence=evidence,
            package_version="1.0",
            dry_run=False,
            user_id="user-1",
        )

    assert "rule_candidate" in str(exc_info.value)


@pytest.mark.asyncio
async def test_rule_draft_engine_validates_status():
    mock_session = MagicMock()
    engine = RuleDraftEngine(mock_session)

    recommendation = {
        "recommendation_id": "rec-123",
        "type": "rule_candidate",
        "status": "OPEN",
    }
    insight = {"insight_id": "ins-123"}
    evidence = []

    with pytest.raises(ConflictError) as exc_info:
        await engine.create_draft(
            recommendation=recommendation,
            insight=insight,
            evidence=evidence,
            package_version="1.0",
            dry_run=False,
            user_id="user-1",
        )

    assert "ACKNOWLEDGED" in str(exc_info.value)
