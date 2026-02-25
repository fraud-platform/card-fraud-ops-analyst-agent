"""Unit tests for tool base interface."""

import pytest

from app.tools.base import BaseTool


class TestBaseTool:
    """Tests for BaseTool ABC."""

    def test_base_tool_requires_name(self):
        """BaseTool subclasses must implement name property."""

        class IncompleteTool(BaseTool):
            @property
            def description(self) -> str:
                return "Incomplete tool"

            async def execute(self, state):
                return state

        with pytest.raises(TypeError):
            IncompleteTool()

    def test_base_tool_requires_description(self):
        """BaseTool subclasses must implement description property."""

        class IncompleteTool(BaseTool):
            @property
            def name(self) -> str:
                return "incomplete_tool"

            async def execute(self, state):
                return state

        with pytest.raises(TypeError):
            IncompleteTool()

    def test_base_tool_requires_execute(self):
        """BaseTool subclasses must implement execute method."""

        class IncompleteTool(BaseTool):
            @property
            def name(self) -> str:
                return "incomplete_tool"

            @property
            def description(self) -> str:
                return "Incomplete tool"

        with pytest.raises(TypeError):
            IncompleteTool()

    def test_complete_tool_instantiable(self, mock_tool_factory):
        """Complete tool implementation can be instantiated."""
        tool = mock_tool_factory("test_tool", "A test tool")
        assert tool.name == "test_tool"
        assert tool.description == "A test tool"
