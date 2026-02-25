"""Unit tests for context tool."""

from unittest.mock import AsyncMock

import pytest

from app.tools.context_tool import ContextTool


class TestContextTool:
    """Tests for ContextTool."""

    def test_name(self):
        """ContextTool has correct name."""
        tool = ContextTool(tm_client=AsyncMock())
        assert tool.name == "context_tool"

    def test_description(self):
        """ContextTool has description."""
        tool = ContextTool(tm_client=AsyncMock())
        assert "transaction" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_fetches_overview(self, initial_state, mock_tm_client):
        """ContextTool fetches transaction overview."""
        tool = ContextTool(tm_client=mock_tm_client)
        result = await tool.execute(initial_state)

        mock_tm_client.get_transaction_overview.assert_called_once()
        assert "context" in result

    @pytest.mark.asyncio
    async def test_execute_fetches_card_history(self, initial_state, mock_tm_client):
        """ContextTool fetches card history when card_id exists."""
        tool = ContextTool(tm_client=mock_tm_client)
        await tool.execute(initial_state)

        mock_tm_client.get_card_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_fetches_merchant_history(self, initial_state, mock_tm_client):
        """ContextTool fetches merchant history when merchant_id exists."""
        tool = ContextTool(tm_client=mock_tm_client)
        await tool.execute(initial_state)

        mock_tm_client.get_merchant_history.assert_called_once()

    @pytest.mark.asyncio
    async def test_execute_skips_if_context_populated(self, state_with_context, mock_tm_client):
        """ContextTool skips TM API calls if context already populated."""
        tool = ContextTool(tm_client=mock_tm_client)
        result = await tool.execute(state_with_context)

        mock_tm_client.get_transaction_overview.assert_not_called()
        assert result == state_with_context

    @pytest.mark.asyncio
    async def test_execute_handles_missing_card_id(self, initial_state, mock_tm_client):
        """ContextTool handles missing card_id gracefully."""
        mock_tm_client.get_transaction_overview.return_value = {
            "transaction": {"transaction_id": "txn-test-123", "amount": 100.0},
            "review": None,
            "notes": [],
            "case": None,
            "matched_rules": [],
        }
        tool = ContextTool(tm_client=mock_tm_client)
        result = await tool.execute(initial_state)

        assert "context" in result
        mock_tm_client.get_card_history.assert_not_called()

    @pytest.mark.asyncio
    async def test_execute_handles_card_history_error(self, initial_state, mock_tm_client):
        """ContextTool handles card history fetch errors gracefully."""
        mock_tm_client.get_card_history.side_effect = Exception("API error")
        tool = ContextTool(tm_client=mock_tm_client)
        result = await tool.execute(initial_state)

        assert "context" in result
