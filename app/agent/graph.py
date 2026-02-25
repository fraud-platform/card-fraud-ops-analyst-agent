"""LangGraph investigation graph construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.completion import completion_node
from app.agent.executor import executor_node
from app.agent.planner import planner_node
from app.agent.state import InvestigationState

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from app.agent.registry import ToolRegistry
    from app.core.config import Settings
    from app.persistence.state_store import PostgresStateStore


def build_investigation_graph(
    registry: ToolRegistry,
    llm: BaseChatModel,
    settings: Settings,
    state_store: PostgresStateStore | None = None,
) -> CompiledStateGraph:
    """Build and compile the investigation StateGraph."""

    async def planner(state: InvestigationState) -> InvestigationState:
        return await planner_node(state, llm, registry)

    async def executor(state: InvestigationState) -> InvestigationState:
        return await executor_node(state, registry)

    async def completion(state: InvestigationState) -> InvestigationState:
        return await completion_node(state, state_store)

    builder = StateGraph(InvestigationState)

    builder.add_node("planner", planner)
    builder.add_node("tool_executor", executor)
    builder.add_node("completion", completion)

    builder.set_entry_point("planner")

    def route_after_planner(state: InvestigationState) -> str:
        if state["next_action"] == "COMPLETE":
            return "completion"
        if state["step_count"] >= state["max_steps"]:
            return "completion"
        return "tool_executor"

    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "tool_executor": "tool_executor",
            "completion": "completion",
        },
    )

    builder.add_edge("tool_executor", "planner")
    builder.add_edge("completion", END)

    return builder.compile()
