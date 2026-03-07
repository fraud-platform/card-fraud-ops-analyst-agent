"""Unit tests for LinkAnalysisTool."""

from __future__ import annotations

import copy
from unittest.mock import AsyncMock

import pytest

from app.core.errors import ToolPreconditionError
from app.tools.link_analysis_tool import LinkAnalysisTool


class TestLinkAnalysisTool:
    def test_name(self) -> None:
        tool = LinkAnalysisTool()
        assert tool.name == "link_analysis_tool"

    def test_description(self) -> None:
        tool = LinkAnalysisTool()
        assert "link" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_requires_context(self, initial_state) -> None:
        tool = LinkAnalysisTool()
        with pytest.raises(ToolPreconditionError):
            await tool.execute(initial_state)

    @pytest.mark.asyncio
    async def test_execute_populates_results_and_evidence(self, state_with_context) -> None:
        tool = LinkAnalysisTool()
        state = {
            **state_with_context,
            "context": {
                **state_with_context["context"],
                "transaction": {
                    "transaction_id": "txn-test-123",
                    "card_id": "card-001",
                    "merchant_id": "merch-001",
                    "transaction_timestamp": "2026-02-28T12:00:00Z",
                    "amount": 120.0,
                    "currency": "USD",
                },
                "card_history": [
                    {
                        "merchant_id": "m-1",
                        "transaction_timestamp": "2026-02-28T11:58:00Z",
                    },
                    {
                        "merchant_id": "m-2",
                        "transaction_timestamp": "2026-02-28T11:57:00Z",
                    },
                    {
                        "merchant_id": "m-3",
                        "transaction_timestamp": "2026-02-28T11:56:00Z",
                    },
                ],
                "merchant_history": [
                    {
                        "card_id": "card-a",
                        "transaction_timestamp": "2026-02-28T11:45:00Z",
                    },
                    {
                        "card_id": "card-b",
                        "transaction_timestamp": "2026-02-28T11:46:00Z",
                    },
                    {
                        "card_id": "card-c",
                        "transaction_timestamp": "2026-02-28T11:47:00Z",
                    },
                    {
                        "card_id": "card-d",
                        "transaction_timestamp": "2026-02-28T11:48:00Z",
                    },
                    {
                        "card_id": "card-e",
                        "transaction_timestamp": "2026-02-28T11:49:00Z",
                    },
                    {
                        "card_id": "card-f",
                        "transaction_timestamp": "2026-02-28T11:50:00Z",
                    },
                    {
                        "card_id": "card-g",
                        "transaction_timestamp": "2026-02-28T11:51:00Z",
                    },
                    {
                        "card_id": "card-h",
                        "transaction_timestamp": "2026-02-28T11:52:00Z",
                    },
                ],
            },
        }

        result = await tool.execute(state)

        assert "link_analysis_results" in result
        assert result["link_analysis_results"]["overall_score"] >= 0.0
        assert isinstance(result["link_analysis_results"]["signals"], list)
        assert result["evidence"][-1]["category"] == "link_analysis"

    @pytest.mark.asyncio
    async def test_execute_is_deterministic_for_same_input(self, state_with_context) -> None:
        tool = LinkAnalysisTool()
        state = {
            **state_with_context,
            "context": {
                **state_with_context["context"],
                "transaction": {
                    "transaction_id": "txn-test-123",
                    "card_id": "card-001",
                    "merchant_id": "merch-001",
                    "transaction_timestamp": "2026-02-28T12:00:00Z",
                },
                "card_history": [
                    {
                        "merchant_id": "m-1",
                        "transaction_timestamp": "2026-02-28T11:58:00Z",
                    },
                    {
                        "merchant_id": "m-2",
                        "transaction_timestamp": "2026-02-28T11:57:00Z",
                    },
                ],
                "merchant_history": [
                    {
                        "card_id": "card-a",
                        "transaction_timestamp": "2026-02-28T11:55:00Z",
                    },
                    {
                        "card_id": "card-b",
                        "transaction_timestamp": "2026-02-28T11:54:00Z",
                    },
                ],
            },
        }

        result_a = await tool.execute(copy.deepcopy(state))
        result_b = await tool.execute(copy.deepcopy(state))

        assert result_a["link_analysis_results"] == result_b["link_analysis_results"]

    @pytest.mark.asyncio
    async def test_execute_enriches_with_tm_neighborhood_clusters(self, state_with_context) -> None:
        tm_client = AsyncMock()
        tm_client.get_ip_neighborhood.return_value = [
            {"transaction_id": "txn-a", "card_id": "card-a"},
            {"transaction_id": "txn-b", "card_id": "card-b"},
            {"transaction_id": "txn-c", "card_id": "card-c"},
            {"transaction_id": "txn-d", "card_id": "card-d"},
        ]
        tm_client.get_device_neighborhood.return_value = []
        tm_client.get_device_fingerprint_neighborhood.return_value = []

        tool = LinkAnalysisTool(tm_client=tm_client)
        state = {
            **state_with_context,
            "context": {
                **state_with_context["context"],
                "transaction": {
                    "transaction_id": "txn-current",
                    "card_id": "card-001",
                    "merchant_id": "merch-001",
                    "transaction_timestamp": "2026-02-28T12:00:00Z",
                },
                "features": {
                    "ip_address": "203.0.113.10",
                },
            },
        }

        result = await tool.execute(state)

        metrics = result["link_analysis_results"]["metrics"]["neighborhood_clusters"]
        assert metrics["ip_neighbor_count"] == 4
        assert "ip_cluster_signature" in result["link_analysis_results"]["signals"]
        tm_client.get_ip_neighborhood.assert_awaited_once_with("203.0.113.10")

    @pytest.mark.asyncio
    async def test_execute_handles_tm_neighborhood_errors(self, state_with_context) -> None:
        tm_client = AsyncMock()
        tm_client.get_ip_neighborhood.side_effect = RuntimeError("tm unavailable")
        tm_client.get_device_neighborhood.return_value = []
        tm_client.get_device_fingerprint_neighborhood.return_value = []

        tool = LinkAnalysisTool(tm_client=tm_client)
        state = {
            **state_with_context,
            "context": {
                **state_with_context["context"],
                "transaction": {
                    "transaction_id": "txn-current",
                    "card_id": "card-001",
                    "merchant_id": "merch-001",
                    "transaction_timestamp": "2026-02-28T12:00:00Z",
                },
                "features": {
                    "ip_address": "203.0.113.10",
                },
            },
        }

        result = await tool.execute(state)

        assert "link_analysis_results" in result
        assert result["evidence"][-1]["category"] == "link_analysis"
