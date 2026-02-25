"""Completion node - finalizes investigation and persists results (TDD-002 §7).

Steps:
1. Set status=COMPLETED, completed_at
2. Compute final confidence_score
3. Determine final severity
4. Persist state → state_store
5. Emit Prometheus metrics
6. Return final state

Persistence of tool logs, insights, recommendations, and audit entries
is handled by InvestigationService after graph completion, keeping the
completion node fast and focused.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import structlog
from opentelemetry import trace

from app.agent.state import InvestigationState
from app.core.metrics import (
    ops_agent_investigation_completed_total,
    ops_agent_investigation_steps,
)
from app.utils.clock import utc_now

if TYPE_CHECKING:
    from app.persistence.state_store import PostgresStateStore

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

# Confidence thresholds are only used as a fallback when state severity is invalid.
_SEVERITY_THRESHOLDS = [
    (0.8, "CRITICAL"),
    (0.6, "HIGH"),
    (0.3, "MEDIUM"),
    (0.0, "LOW"),
]
_VALID_SEVERITIES = {"LOW", "MEDIUM", "HIGH", "CRITICAL"}


def _compute_final_confidence(state: InvestigationState) -> float:
    """Compute final confidence score from evidence and reasoning.

    Averages pattern confidence, similarity score, and reasoning confidence,
    weighted toward pattern results.
    """
    scores: list[float] = []

    # Pattern confidence
    pattern_conf = state.get("pattern_results", {}).get("overall_confidence", 0.0)
    if pattern_conf:
        scores.append(float(pattern_conf))

    # Similarity score
    sim_score = state.get("similarity_results", {}).get("overall_score", 0.0)
    if sim_score:
        scores.append(float(sim_score))

    # Reasoning confidence
    reasoning_conf = state.get("reasoning", {}).get("confidence", 0.0)
    if reasoning_conf:
        scores.append(float(reasoning_conf))

    if not scores:
        return state.get("confidence_score", 0.0)

    return round(sum(scores) / len(scores), 4)


def _determine_severity(confidence: float, current_severity: str) -> str:
    """Determine final severity.

    Confidence reflects certainty, not risk magnitude. Keep the severity selected
    by the tools/reasoning whenever valid. Only derive from confidence as a
    defensive fallback for malformed state.
    """
    normalized = (current_severity or "").upper()
    if normalized in _VALID_SEVERITIES:
        return normalized

    for threshold, level in _SEVERITY_THRESHOLDS:
        if confidence >= threshold:
            return level
    return "LOW"


async def completion_node(
    state: InvestigationState,
    state_store: PostgresStateStore | None = None,
) -> InvestigationState:
    """Finalize investigation and persist results."""
    with tracer.start_as_current_span("agent.completion") as span:
        investigation_id = state["investigation_id"]
        span.set_attribute("investigation_id", investigation_id)

        completed_at = utc_now().isoformat()

        # Step 2: Compute final confidence
        confidence = _compute_final_confidence(state)

        # Step 3: Determine final severity
        severity = _determine_severity(confidence, state.get("severity", "LOW"))

        final_state: InvestigationState = {
            **state,
            "status": "COMPLETED",
            "completed_at": completed_at,
            "confidence_score": confidence,
            "severity": severity,
        }

        span.set_attribute("confidence_score", confidence)
        span.set_attribute("severity", severity)
        span.set_attribute("step_count", state.get("step_count", 0))

        # Step 4: Persist state
        if state_store is not None:
            try:
                await state_store.save_state(
                    investigation_id=investigation_id,
                    state=dict(final_state),
                )
            except Exception:
                logger.error(
                    "Failed to persist final state",
                    investigation_id=investigation_id,
                    exc_info=True,
                )
                span.set_attribute("state_persist_error", True)

        # Step 5: Emit Prometheus metrics
        ops_agent_investigation_completed_total.labels(status="COMPLETED", severity=severity).inc()
        ops_agent_investigation_steps.labels(status="COMPLETED").observe(state.get("step_count", 0))

        logger.info(
            "Investigation completed",
            investigation_id=investigation_id,
            severity=severity,
            confidence=confidence,
            step_count=state.get("step_count", 0),
            tool_count=len(state.get("completed_steps", [])),
            recommendation_count=len(state.get("recommendations", [])),
        )

        return final_state
