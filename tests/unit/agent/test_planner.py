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

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        return _DummyResponse(content=self._content)


class _SequenceLLM:
    def __init__(self, contents: list[str]) -> None:
        self._contents = contents
        self._index = 0

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        if self._index >= len(self._contents):
            value = self._contents[-1]
        else:
            value = self._contents[self._index]
        self._index += 1
        return _DummyResponse(content=value)


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
        "link_analysis_tool",
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
    """LLM choosing an already-completed tool should trigger sequence fallback."""
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

    updated_state = asyncio.run(planner_node(state, llm, registry))

    assert updated_state["next_action"] == "link_analysis_tool"
    assert "rule-sequence fallback" in updated_state["planner_decisions"][-1]["reason"]


class _FailingLLM:
    """LLM that always raises an exception — simulates empty-content error."""

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        raise ValueError("LLM returned empty content after 2 attempts")


class _RepeatToolLLM:
    """LLM that returns an already-completed tool name."""

    def __init__(self, tool: str) -> None:
        self._tool = tool

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        return _DummyResponse(
            content=json.dumps({"tool": self._tool, "reason": "repeat", "confidence": 0.5})
        )


class _BadJsonLLM:
    """LLM that returns invalid JSON — simulates parse failure path."""

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        return _DummyResponse(content="not json at all")


class _CountingFailingLLM:
    """LLM that always fails while tracking invocation count."""

    def __init__(self) -> None:
        self.calls = 0

    async def ainvoke(self, _messages, **_kwargs):  # noqa: ANN001, ANN003
        self.calls += 1
        raise ValueError("planner unavailable")


def test_planner_uses_rule_sequence_fallback_on_llm_error() -> None:
    """When LLM fails, planner should choose next tool via sequence fallback."""
    state = create_initial_state("inv-3", "txn-3")
    state["context"] = {"transaction": {"transaction_id": "txn-3"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    registry = _build_registry()
    updated_state = asyncio.run(planner_node(state, _FailingLLM(), registry))

    assert updated_state["next_action"] == "similarity_tool"
    assert "rule-sequence fallback" in updated_state["planner_decisions"][-1]["reason"]


def test_planner_rule_sequence_fallback_returns_complete_when_all_done() -> None:
    """When all sequence tools are done, fallback should return COMPLETE."""
    state = create_initial_state("inv-4", "txn-4")
    state["context"] = {"transaction": {"transaction_id": "txn-4"}}
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "link_analysis_tool",
        "reasoning_tool",
        "recommendation_tool",
    ]
    state["step_count"] = 5

    registry = _build_registry()
    updated_state = asyncio.run(planner_node(state, _FailingLLM(), registry))

    assert updated_state["next_action"] == "COMPLETE"
    assert "all tools completed" in updated_state["planner_decisions"][-1]["reason"]


def test_planner_rule_sequence_fallback_attempts_rule_draft_for_high_severity() -> None:
    """Fallback should attempt rule_draft_tool for high severity investigations."""
    state = create_initial_state("inv-4b", "txn-4b")
    state["context"] = {"transaction": {"transaction_id": "txn-4b"}}
    state["severity"] = "HIGH"
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "link_analysis_tool",
        "reasoning_tool",
        "recommendation_tool",
    ]
    state["step_count"] = 5

    registry = _build_registry()
    updated_state = asyncio.run(planner_node(state, _FailingLLM(), registry))

    assert updated_state["next_action"] == "rule_draft_tool"
    assert "rule draft required" in updated_state["planner_decisions"][-1]["reason"]


def test_planner_falls_back_when_llm_picks_repeated_tool() -> None:
    """When LLM repeats a completed tool, planner should fall back to sequence."""
    state = create_initial_state("inv-5", "txn-5")
    state["context"] = {"transaction": {"transaction_id": "txn-5"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    registry = _build_registry()
    updated_state = asyncio.run(planner_node(state, _RepeatToolLLM("pattern_tool"), registry))

    assert updated_state["next_action"] == "similarity_tool"
    assert "rule-sequence fallback" in updated_state["planner_decisions"][-1]["reason"]


def test_planner_parse_failure_uses_fallback_not_crash() -> None:
    """Invalid LLM JSON should trigger sequence fallback without crashing."""
    state = create_initial_state("inv-6", "txn-6")
    state["context"] = {"transaction": {"transaction_id": "txn-6"}}
    state["completed_steps"] = ["context_tool"]
    state["step_count"] = 1

    registry = _build_registry()
    updated_state = asyncio.run(planner_node(state, _BadJsonLLM(), registry))

    assert updated_state["next_action"] == "pattern_tool"
    assert "rule-sequence fallback" in updated_state["planner_decisions"][-1]["reason"]


def test_planner_opens_circuit_after_first_llm_failure() -> None:
    """Planner should open fallback circuit after first LLM failure."""
    state = create_initial_state("inv-7", "txn-7")
    state["context"] = {"transaction": {"transaction_id": "txn-7"}}
    state["completed_steps"] = ["context_tool", "pattern_tool"]
    state["step_count"] = 2

    registry = _build_registry()
    llm = _CountingFailingLLM()

    first_state = asyncio.run(planner_node(state, llm, registry))
    assert llm.calls == 1
    assert first_state["next_action"] == "similarity_tool"

    second_state = asyncio.run(planner_node(first_state, llm, registry))
    assert second_state["next_action"] == "similarity_tool"
    assert llm.calls == 1


def test_planner_repairs_invalid_complete_decision() -> None:
    """Planner should repair a premature COMPLETE decision and continue."""
    state = create_initial_state("inv-8", "txn-8")
    state["context"] = {"transaction": {"transaction_id": "txn-8"}}
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "link_analysis_tool",
    ]
    state["step_count"] = 4

    llm = _SequenceLLM(
        [
            json.dumps(
                {
                    "tool": "COMPLETE",
                    "reason": "Done",
                    "confidence": 0.9,
                }
            ),
            json.dumps(
                {
                    "tool": "reasoning_tool",
                    "reason": "Need reasoning before completion",
                    "confidence": 0.8,
                }
            ),
        ]
    )
    registry = _build_registry()

    updated_state = asyncio.run(planner_node(state, llm, registry))
    assert updated_state["next_action"] == "reasoning_tool"
    assert updated_state["step_count"] == 5


def test_planner_falls_back_when_repair_does_not_fix_invalid_decision() -> None:
    """Planner should fall back when repair loop still yields invalid decisions."""
    state = create_initial_state("inv-9", "txn-9")
    state["context"] = {"transaction": {"transaction_id": "txn-9"}}
    state["completed_steps"] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "link_analysis_tool",
    ]
    state["step_count"] = 4

    llm = _SequenceLLM(
        [
            json.dumps(
                {
                    "tool": "COMPLETE",
                    "reason": "Done",
                    "confidence": 0.9,
                }
            ),
            json.dumps(
                {
                    "tool": "COMPLETE",
                    "reason": "Still done",
                    "confidence": 0.9,
                }
            ),
        ]
    )
    registry = _build_registry()

    updated_state = asyncio.run(planner_node(state, llm, registry))

    assert updated_state["next_action"] == "reasoning_tool"
    assert "rule-sequence fallback" in updated_state["planner_decisions"][-1]["reason"]
