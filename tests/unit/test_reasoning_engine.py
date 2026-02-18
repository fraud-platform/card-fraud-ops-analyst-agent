"""Unit tests for reasoning engine (stub)."""

import pytest

from app.agents.reasoning_engine import ReasoningEngine
from app.core.config import reload_settings


@pytest.mark.asyncio
async def test_reasoning_engine_returns_none(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPS_AGENT_ENABLE_LLM_REASONING", "false")
    reload_settings()
    engine = ReasoningEngine()
    result = await engine.reason({}, {}, {})
    assert result is None
    monkeypatch.delenv("OPS_AGENT_ENABLE_LLM_REASONING", raising=False)
    reload_settings()
