"""Unit tests for pattern engine adapter."""

import json
from unittest.mock import AsyncMock

import pytest

from app.agents.pattern_engine import PatternEngine


@pytest.mark.asyncio
async def test_pattern_engine_analyze():
    """Test pattern engine analysis."""
    mock_session = AsyncMock()
    engine = PatternEngine(mock_session)

    # Use empty context that won't trigger signals
    mock_context = {
        "transaction": {"transaction_id": "txn-123"},
        "window_stats": {},
        "signals": [],
    }

    result = await engine.analyze(mock_context)

    print("\n[PATTERN_ENGINE] Input context:")
    print(f"  {json.dumps(mock_context, indent=2, default=str)}")
    print("[PATTERN_ENGINE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert "pattern_scores" in result
    assert "severity" in result
    assert isinstance(result["pattern_scores"], list)
    assert result["severity"] in ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


@pytest.mark.asyncio
async def test_pattern_engine_analyze_empty_context():
    """Test pattern engine with empty context."""
    mock_session = AsyncMock()
    engine = PatternEngine(mock_session)

    mock_context = {}

    result = await engine.analyze(mock_context)

    print("\n[PATTERN_ENGINE] Empty context input")
    print(f"[PATTERN_ENGINE] Output severity: {result['severity']}")
    print(f"[PATTERN_ENGINE] Pattern scores count: {len(result['pattern_scores'])}")

    assert result["severity"] == "LOW"
    assert len(result["pattern_scores"]) >= 3  # velocity, decline, cross_merchant scores
