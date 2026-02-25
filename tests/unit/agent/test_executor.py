"""Unit tests for executor node behavior."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace

from app.agent.executor import executor_node
from app.agent.registry import ToolRegistry
from app.agent.state import create_initial_state
from app.tools.base import BaseTool


class _PatternTool(BaseTool):
    @property
    def name(self) -> str:
        return "pattern_tool"

    @property
    def description(self) -> str:
        return "dummy pattern tool"

    async def execute(self, state):  # noqa: ANN001
        return {
            **state,
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.8, "weight": 0.4, "details": {}},
                ],
                "overall_score": 0.8,
                "patterns_detected": ["velocity"],
            },
            "severity": "HIGH",
        }


class _SimilarityTool(BaseTool):
    @property
    def name(self) -> str:
        return "similarity_tool"

    @property
    def description(self) -> str:
        return "dummy similarity tool"

    async def execute(self, state):  # noqa: ANN001
        return {
            **state,
            "similarity_results": {
                "overall_score": 0.62,
                "matches": [
                    {
                        "match_id": "txn-prev-1",
                        "match_type": "precomputed",
                        "similarity_score": 0.62,
                    }
                ],
                "vector_diagnostics": {
                    "candidate_count": 7,
                    "search_limit": 20,
                    "min_similarity": 0.3,
                    "embedding_model": "mxbai-embed-large",
                    "embedding_dimension": 1024,
                    "reason": None,
                },
            },
            "severity": "MEDIUM",
        }


class _FailingReasoningTool(BaseTool):
    @property
    def name(self) -> str:
        return "reasoning_tool"

    @property
    def description(self) -> str:
        return "failing reasoning tool"

    async def execute(self, state):  # noqa: ANN001
        raise RuntimeError("simulated reasoning timeout")


def test_executor_records_input_and_output_summaries() -> None:
    state = create_initial_state("inv-exec-1", "txn-exec-1")
    state["context"] = {
        "transaction": {
            "transaction_id": "txn-exec-1",
            "amount": 99.0,
            "currency": "USD",
            "decision": "DECLINE",
            "card_id": "card-1",
            "merchant_id": "merchant-1",
        },
        "windows": {"1": {"transaction_count": 3}},
        "signals": [{"name": "burst_1h", "value": True}],
        "rule_matches": [{"rule_name": "VELOCITY_BURST_1H"}],
        "card_history": [{"transaction_id": "hist-1"}],
    }
    state["completed_steps"] = ["context_tool"]
    state["step_count"] = 1
    state["next_action"] = "pattern_tool"

    registry = ToolRegistry()
    registry.register(_PatternTool())

    result = asyncio.run(executor_node(state, registry))

    execution = result["tool_executions"][-1]
    assert execution["status"] == "SUCCESS"
    assert execution["input_summary"]["transaction_id"] == "txn-exec-1"
    assert execution["input_summary"]["context"]["window_counts"]["1"] == 3
    assert execution["output_summary"]["pattern_results"]["patterns_detected"] == ["velocity"]
    assert result["severity"] == "HIGH"


def test_executor_similarity_summary_includes_vector_diagnostics() -> None:
    state = create_initial_state("inv-exec-2", "txn-exec-2")
    state["context"] = {
        "transaction": {
            "transaction_id": "txn-exec-2",
            "amount": 119.0,
            "currency": "USD",
            "decision": "DECLINE",
            "card_id": "card-2",
            "merchant_id": "merchant-2",
        },
        "windows": {"1": {"transaction_count": 2}},
        "signals": [],
        "rule_matches": [],
        "card_history": [],
    }
    state["pattern_results"] = {
        "scores": [],
        "overall_score": 0.0,
        "patterns_detected": [],
    }
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2
    state["next_action"] = "similarity_tool"

    registry = ToolRegistry()
    registry.register(_SimilarityTool())

    result = asyncio.run(executor_node(state, registry))
    execution = result["tool_executions"][-1]
    similarity_summary = execution["output_summary"]["similarity_results"]

    assert similarity_summary["match_count"] == 1
    assert similarity_summary["vector_diagnostics"]["candidate_count"] == 7
    assert similarity_summary["vector_diagnostics"]["embedding_dimension"] == 1024


def test_executor_context_summary_supports_object_transaction() -> None:
    state = create_initial_state("inv-exec-3", "txn-exec-3")
    state["context"] = {
        "transaction": SimpleNamespace(
            transaction_id="txn-exec-3",
            amount=77.0,
            currency="USD",
            status="DECLINE",
            card_id="card-3",
            merchant_id="merchant-3",
        ),
        "windows": {"1": {"transaction_count": 4}},
        "signals": [{"name": "has_rule_matches", "value": 1}],
        "rule_matches": [{"rule_name": "VELOCITY_SHORT_TERM"}],
        "card_history": [{"transaction_id": "hist-2"}],
    }
    state["completed_steps"] = []
    state["step_count"] = 1
    state["next_action"] = "pattern_tool"

    registry = ToolRegistry()
    registry.register(_PatternTool())

    result = asyncio.run(executor_node(state, registry))
    execution = result["tool_executions"][-1]
    context_summary = execution["input_summary"]["context"]

    assert context_summary["transaction_id"] == "txn-exec-3"
    assert context_summary["amount"] == 77.0
    assert context_summary["decision"] == "DECLINE"
    assert context_summary["card_id"] == "***REDACTED***"


def test_executor_reasoning_failure_summary_includes_llm_status() -> None:
    state = create_initial_state("inv-exec-4", "txn-exec-4")
    state["context"] = {
        "transaction": {
            "transaction_id": "txn-exec-4",
            "amount": 40.0,
            "currency": "USD",
            "decision": "APPROVE",
            "card_id": "card-4",
            "merchant_id": "merchant-4",
        },
        "windows": {"1": {"transaction_count": 1}},
        "signals": [],
        "rule_matches": [],
        "card_history": [],
    }
    state["pattern_results"] = {"scores": [], "overall_score": 0.0, "patterns_detected": []}
    state["similarity_results"] = {"overall_score": 0.0, "matches": []}
    state["completed_steps"] = ["context_tool", "pattern_tool", "similarity_tool"]
    state["step_count"] = 3
    state["next_action"] = "reasoning_tool"

    registry = ToolRegistry()
    registry.register(_FailingReasoningTool())

    result = asyncio.run(executor_node(state, registry))
    execution = result["tool_executions"][-1]
    assert execution["status"] == "FAILED"
    assert execution["output_summary"]["reasoning"]["llm_status"] == "failed"
