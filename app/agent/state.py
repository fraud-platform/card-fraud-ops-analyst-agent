"""Investigation state model for LangGraph agent runtime.

Central state object passed through all graph nodes.
Persisted in PostgreSQL as JSONB after every step.
"""

from __future__ import annotations

from typing import Any, TypedDict

from app.utils.clock import utc_now


class ToolExecution(TypedDict):
    """Record of a single tool execution within an investigation."""

    tool_name: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    execution_time_ms: int
    status: str
    error_message: str | None
    timestamp: str


class PlannerDecision(TypedDict):
    """Record of a single planner decision."""

    step: int
    selected_tool: str
    reason: str
    confidence: float
    timestamp: str
    llm_prompt_preview: str | None
    llm_response_preview: str | None


class InvestigationState(TypedDict):
    """Central state object for LangGraph investigation graph.

    All fields have sensible defaults via create_initial_state().
    State is immutable-by-convention - nodes return new state dicts.
    Fully JSON-serializable - no datetime/UUID objects (all strings).
    """

    investigation_id: str
    transaction_id: str
    case_id: str | None
    scenario_name: str | None
    trace_id: str | None
    model_mode: str

    context: dict[str, Any]

    pattern_results: dict[str, Any]
    similarity_results: dict[str, Any]
    hypotheses: list[dict[str, Any] | str]
    evidence: list[dict[str, Any]]

    reasoning: dict[str, Any]

    recommendations: list[dict[str, Any]]
    rule_draft: dict[str, Any] | None

    confidence_score: float
    severity: str

    status: str
    completed_steps: list[str]
    next_action: str
    step_count: int
    max_steps: int
    started_at: str
    completed_at: str | None

    planner_decisions: list[PlannerDecision]
    tool_executions: list[ToolExecution]
    error: str | None

    # Runtime feature flags snapshot (TDD-002 sec. 2)
    feature_flags: dict[str, bool]
    # Runtime safeguards snapshot (TDD-002 sec. 2)
    safeguards: dict[str, int]


def create_initial_state(
    investigation_id: str,
    transaction_id: str,
    max_steps: int = 20,
    *,
    case_id: str | None = None,
    scenario_name: str | None = None,
    trace_id: str | None = None,
    feature_flags: dict[str, bool] | None = None,
    safeguards: dict[str, int] | None = None,
) -> InvestigationState:
    """Create a fresh investigation state with sensible defaults."""
    return InvestigationState(
        investigation_id=investigation_id,
        transaction_id=transaction_id,
        case_id=case_id,
        scenario_name=scenario_name,
        trace_id=trace_id,
        model_mode="agentic",
        context={},
        pattern_results={},
        similarity_results={},
        hypotheses=[],
        evidence=[],
        reasoning={},
        recommendations=[],
        rule_draft=None,
        confidence_score=0.0,
        severity="LOW",
        status="PENDING",
        completed_steps=[],
        next_action="",
        step_count=0,
        max_steps=max_steps,
        started_at=utc_now().isoformat(),
        completed_at=None,
        planner_decisions=[],
        tool_executions=[],
        error=None,
        feature_flags=feature_flags or {},
        safeguards=safeguards or {},
    )


def update_state(state: InvestigationState, **updates: Any) -> InvestigationState:
    """Return a new state dict with the given fields merged.

    Convenience helper that replaces the repetitive ``{**state, "key": val}``
    pattern used in every tool.  Keeps tool code focused on *what* changed
    rather than the mechanics of dict-spread.

    >>> s = create_initial_state("inv-1", "txn-1")
    >>> s2 = update_state(s, severity="HIGH", confidence_score=0.85)
    >>> s2["severity"]
    'HIGH'
    """
    return {**state, **updates}  # type: ignore[return-value]
