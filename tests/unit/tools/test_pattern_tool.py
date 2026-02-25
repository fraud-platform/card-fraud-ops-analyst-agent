"""Unit tests for pattern tool."""

import pytest

from app.core.errors import ToolPreconditionError
from app.tools.pattern_tool import PatternTool


class TestPatternTool:
    """Tests for PatternTool."""

    def test_name(self):
        """PatternTool has correct name."""
        tool = PatternTool()
        assert tool.name == "pattern_tool"

    def test_description(self):
        """PatternTool has description."""
        tool = PatternTool()
        assert "pattern" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_requires_context(self, initial_state):
        """PatternTool raises error if context is missing."""
        tool = PatternTool()
        with pytest.raises(ToolPreconditionError):
            await tool.execute(initial_state)

    @pytest.mark.asyncio
    async def test_execute_with_context(self, state_with_context):
        """PatternTool runs analysis when context exists."""
        tool = PatternTool()
        result = await tool.execute(state_with_context)

        assert "pattern_results" in result
        assert "scores" in result["pattern_results"]
        assert "evidence" in result

    @pytest.mark.asyncio
    async def test_execute_adds_evidence(self, state_with_context):
        """PatternTool adds evidence entry."""
        tool = PatternTool()
        initial_evidence_count = len(state_with_context.get("evidence", []))
        result = await tool.execute(state_with_context)

        assert len(result["evidence"]) > initial_evidence_count

    @pytest.mark.asyncio
    async def test_execute_updates_severity(self, state_with_context):
        """PatternTool updates severity based on patterns."""
        state_with_context["context"]["transaction"]["amount"] = 9999.99
        tool = PatternTool()
        result = await tool.execute(state_with_context)

        assert "severity" in result
