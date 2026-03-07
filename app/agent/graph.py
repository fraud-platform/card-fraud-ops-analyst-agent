"""LangGraph investigation graph construction."""

from __future__ import annotations

from typing import TYPE_CHECKING

from langgraph.graph import END, StateGraph
from langgraph.graph.state import CompiledStateGraph

from app.agent.completion import completion_node
from app.agent.executor import executor_node
from app.agent.planner import planner_node
from app.agent.state import InvestigationState
from app.core.errors import PlannerError

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

    async def _save_state(state: InvestigationState) -> None:
        if state_store is None:
            return
        try:
            await state_store.save_state(
                investigation_id=state["investigation_id"],
                state=dict(state),
            )
        except Exception:
            # Best-effort recovery for shared SQLAlchemy session state.
            try:
                await state_store._session.rollback()  # pyright: ignore[reportPrivateUsage]
            except Exception:
                pass
            # Never fail the graph due to persistence issues.
            return

    async def planner(state: InvestigationState) -> InvestigationState:
        try:
            updated = await planner_node(state, llm, registry)
        except PlannerError as exc:
            # Fail-fast (no fallback): surface the planner failure in state,
            # but do not crash the graph and lose partial progress.
            updated = {
                **state,
                "status": "FAILED",
                "error": str(exc),
                "next_action": "COMPLETE",
            }
        await _save_state(updated)
        return updated

    async def executor(state: InvestigationState) -> InvestigationState:
        updated = await executor_node(state, registry)
        await _save_state(updated)
        return updated

    async def completion(state: InvestigationState) -> InvestigationState:
        updated = await completion_node(state, state_store)
        await _save_state(updated)
        return updated

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
