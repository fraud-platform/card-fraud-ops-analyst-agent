"""Unit tests for tool registry."""

import pytest

from app.agent.registry import ToolRegistry


class TestToolRegistry:
    """Tests for ToolRegistry."""

    def test_register_and_get(self, mock_tool_factory):
        """Register tool and retrieve by name."""
        registry = ToolRegistry()
        tool = mock_tool_factory("test_tool", "A test tool")

        registry.register(tool)
        retrieved = registry.get("test_tool")

        assert retrieved.name == "test_tool"
        assert retrieved.description == "A test tool"

    def test_get_unknown_raises(self):
        """Unknown tool raises KeyError."""
        registry = ToolRegistry()

        with pytest.raises(KeyError, match="Unknown tool"):
            registry.get("nonexistent")

    def test_list_tools(self, mock_tool_factory):
        """List all registered tools."""
        registry = ToolRegistry()
        registry.register(mock_tool_factory("tool_a"))
        registry.register(mock_tool_factory("tool_b"))

        tools = registry.list_tools()

        assert len(tools) == 2
        names = [t["name"] for t in tools]
        assert "tool_a" in names
        assert "tool_b" in names

    def test_duplicate_registration_raises(self, mock_tool_factory):
        """Cannot register same name twice."""
        registry = ToolRegistry()
        registry.register(mock_tool_factory("tool_a"))

        with pytest.raises(ValueError, match="already registered"):
            registry.register(mock_tool_factory("tool_a"))

    def test_has(self, mock_tool_factory):
        """Check if tool is registered."""
        registry = ToolRegistry()
        registry.register(mock_tool_factory("tool_a"))

        assert registry.has("tool_a") is True
        assert registry.has("nonexistent") is False

    def test_tool_names_sorted(self, mock_tool_factory):
        """Tool names returned sorted."""
        registry = ToolRegistry()
        registry.register(mock_tool_factory("zebra"))
        registry.register(mock_tool_factory("alpha"))
        registry.register(mock_tool_factory("middle"))

        assert registry.tool_names == ["alpha", "middle", "zebra"]
