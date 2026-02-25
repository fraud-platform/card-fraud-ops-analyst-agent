"""Unit tests for planner behavior."""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass

from app.agent.planner import planner_node
from app.agent.registry import ToolRegistry
from app.agent.state import create_initial_state
from app.tools.base import BaseTool


@dataclass
class _DummyResponse:
    content: str
    usage_metadata: dict[str, int] | None = None


class _DummyLLM:
    def __init__(self, content: str) -> None:
        self._content = content

    async def ainvoke(self, _messages):  # noqa: ANN001
        return _DummyResponse(content=self._content)


class _DummyTool(BaseTool):
    def __init__(self, name: str) -> None:
        self._name = name

    @property
    def name(self) -> str:
        return self._name

    @property
    def description(self) -> str:
        return f"Dummy tool: {self._name}"

    async def execute(self, state):  # noqa: ANN001
        return state


def _build_registry() -> ToolRegistry:
    registry = ToolRegistry()
    for tool_name in [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "reasoning_tool",
        "recommendation_tool",
        "rule_draft_tool",
    ]:
        registry.register(_DummyTool(tool_name))
    return registry


def test_planner_requires_context_first() -> None:
    state = create_initial_state("inv-1", "txn-1")
    registry = _build_registry()
    llm = _DummyLLM('{"tool":"pattern_tool","reason":"x","confidence":0.5}')

    updated_state = asyncio.run(planner_node(state, llm, registry))

    assert updated_state["next_action"] == "context_tool"
    assert updated_state["step_count"] == 1


def test_planner_repeated_tool_falls_back_to_rule_sequence() -> None:
    """When LLM picks an already-completed tool the planner falls back, not raises."""
    state = create_initial_state("inv-2", "txn-2")
    state["context"] = {"transaction": {"transaction_id": "txn-2"}}
    state["completed_steps"] = ["context_tool", "pattern_tool", "similarity_tool"]
    state["step_count"] = 3

    llm = _DummyLLM(
        json.dumps(
            {
                "tool": "similarity_tool",
                "reason": "repeat similarity",
                "confidence": 0.5,
            }
        )
    )
    registry = _build_registry()

    updated = asyncio.run(planner_node(state, llm, registry))

    # Falls back to next tool in sequence after the repeated ones
    assert updated["next_action"] == "reasoning_tool"
    assert updated["step_count"] == 4


class _FailingLLM:
    """LLM that always raises an exception — simulates Ollama empty-content error."""

    async def ainvoke(self, _messages):  # noqa: ANN001
        raise ValueError("Ollama empty message.content after 2 attempts")


class _RepeatToolLLM:
    """LLM that returns an already-completed tool name."""

    def __init__(self, tool: str) -> None:
        self._tool = tool

    async def ainvoke(self, _messages):  # noqa: ANN001
        return _DummyResponse(
            content=json.dumps({"tool": self._tool, "reason": "repeat", "confidence": 0.5})
        )


class _BadJsonLLM:
    """LLM that returns invalid JSON — simulates parse failure path."""

    async def ainvoke(self, _messages):  # noqa: ANN001
        return _DummyResponse(content="not json at all")


class _CountingFailingLLM:
    """LLM that always fails while tracking invocation count."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages):  # noqa: ANN001
        self.calls += 1
        raise ValueError("planner unavailable")


def test_planner_uses_rule_sequence_fallback_on_llm_error() -> None:
    """When LLM fails, planner falls back to canonical tool sequence."""
    state = create_initial_state("inv-3", "txn-3")
    state["context"] = {"transaction": {"transaction_id": "txn-3"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    registry = _build_registry()
    updated = asyncio.run(planner_node(state, _FailingLLM(), registry))

    # Canonical sequence after context+pattern = similarity_tool
    assert updated["next_action"] == "similarity_tool"
    assert updated["step_count"] == 3


def test_planner_rule_sequence_fallback_returns_complete_when_all_done() -> None:
    """Rule-sequence fallback returns COMPLETE when all sequence tools are done."""
    state = create_initial_state("inv-4", "txn-4")
    state["context"] = {"transaction": {"transaction_id": "txn-4"}}
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "reasoning_tool",
        "recommendation_tool",
    ]
    state["step_count"] = 5

    registry = _build_registry()
    updated = asyncio.run(planner_node(state, _FailingLLM(), registry))

    assert updated["next_action"] == "COMPLETE"


def test_planner_rule_sequence_fallback_attempts_rule_draft_for_high_severity() -> None:
    """High-severity fallback flow should still execute rule_draft_tool before COMPLETE."""
    state = create_initial_state("inv-4b", "txn-4b")
    state["context"] = {"transaction": {"transaction_id": "txn-4b"}}
    state["severity"] = "HIGH"
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "reasoning_tool",
        "recommendation_tool",
    ]
    state["step_count"] = 5

    registry = _build_registry()
    updated = asyncio.run(planner_node(state, _FailingLLM(), registry))

    assert updated["next_action"] == "rule_draft_tool"


def test_planner_falls_back_when_llm_picks_repeated_tool() -> None:
    """When LLM returns an already-completed tool, planner falls back to rule sequence."""
    state = create_initial_state("inv-5", "txn-5")
    state["context"] = {"transaction": {"transaction_id": "txn-5"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    # LLM picks pattern_tool which is already done
    registry = _build_registry()
    updated = asyncio.run(planner_node(state, _RepeatToolLLM("pattern_tool"), registry))

    # Should skip pattern_tool and pick next in sequence
    assert updated["next_action"] == "similarity_tool"
    assert updated["step_count"] == 3


def test_planner_parse_failure_uses_fallback_not_crash() -> None:
    """Invalid LLM JSON triggers fallback — no TypeError from PlannerError constructor."""
    state = create_initial_state("inv-6", "txn-6")
    state["context"] = {"transaction": {"transaction_id": "txn-6"}}
    state["completed_steps"] = ["context_tool"]
    state["step_count"] = 1

    registry = _build_registry()
    updated = asyncio.run(planner_node(state, _BadJsonLLM(), registry))

    # Fallback after parse error — next after context_tool is pattern_tool
    assert updated["next_action"] == "pattern_tool"
    assert updated["step_count"] == 2


def test_planner_opens_circuit_after_first_llm_failure() -> None:
    """After one planner LLM failure, later steps should skip LLM attempts."""
    state = create_initial_state("inv-7", "txn-7")
    state["context"] = {"transaction": {"transaction_id": "txn-7"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    registry = _build_registry()
    llm = _CountingFailingLLM()

    first = asyncio.run(planner_node(state, llm, registry))
    assert first["next_action"] == "similarity_tool"
    assert llm.calls == 1

    second_input = {
        **first,
        "completed_steps": [*first["completed_steps"], first["next_action"]],
    }
    second = asyncio.run(planner_node(second_input, llm, registry))

    assert second["next_action"] == "reasoning_tool"
    assert "planner circuit open" in str(second["planner_decisions"][-1]["reason"]).lower()
    assert llm.calls == 1
