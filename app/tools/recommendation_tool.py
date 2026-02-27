"""Recommendation tool - generates fraud investigation recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.state import update_state
from app.tools._core.pattern_logic import PatternScore
from app.tools._core.recommendation_logic import generate_recommendations
from app.tools._core.similarity_logic import SimilarityMatch, SimilarityResult
from app.tools.base import BaseTool
from app.utils.constants import SEVERITY_RANK, VALID_SEVERITIES
from app.utils.data_access import as_dict, get_attr

if TYPE_CHECKING:
    from app.agent.state import InvestigationState


class RecommendationTool(BaseTool):
    """Generate fraud investigation recommendations based on evidence and reasoning results."""

    @property
    def name(self) -> str:
        return "recommendation_tool"

    @property
    def description(self) -> str:
        return (
            "Generate fraud investigation recommendations based on evidence and reasoning results"
        )

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = as_dict(state["context"])
        pattern_results = as_dict(state["pattern_results"])
        similarity_results = as_dict(state["similarity_results"])
        reasoning = as_dict(state.get("reasoning"))
        severity = state["severity"]

        # When reasoning succeeded, trust its risk_level to override severity in both
        # directions (fixes no_fraud_overescalated: pattern HIGH + LLM LOW → LOW recs).
        # When reasoning failed/unavailable, only allow an upgrade (preserve existing caution).
        reasoning_status = reasoning.get("llm_status")
        reasoning_risk = reasoning.get("risk_level")
        if reasoning_status == "success" and reasoning_risk in VALID_SEVERITIES:
            severity = reasoning_risk
        else:
            reasoning_severity = reasoning.get("severity")
            if reasoning_severity and reasoning_severity in VALID_SEVERITIES:
                if SEVERITY_RANK.get(reasoning_severity, 0) > SEVERITY_RANK.get(severity, 0):
                    severity = reasoning_severity

        pattern_scores = [
            PatternScore(
                pattern_name=s.get("pattern_name", "unknown"),
                score=float(s.get("score", 0.0)),
                weight=float(s.get("weight", 1.0)),
                details=s.get("details", {}),
            )
            for s in pattern_results.get("scores", [])
        ]

        matches = [
            SimilarityMatch(
                match_id=str(get_attr(m, "match_id") or get_attr(m, "transaction_id", "")),
                match_type=str(get_attr(m, "match_type", "unknown")),
                similarity_score=float(
                    get_attr(m, "similarity_score") or get_attr(m, "score", 0.0)
                ),
                details=(
                    get_attr(m, "details", {})
                    if isinstance(get_attr(m, "details", {}), dict)
                    else {}
                ),
                counter_evidence=(
                    get_attr(m, "counter_evidence")
                    if isinstance(get_attr(m, "counter_evidence"), list)
                    else None
                ),
            )
            for m in similarity_results.get("matches", [])
        ]

        similarity_result = SimilarityResult(
            matches=matches,
            overall_score=float(similarity_results.get("overall_score", 0.0)),
            counter_evidence=similarity_results.get("counter_evidence"),
        )

        candidates = generate_recommendations(
            pattern_scores=pattern_scores,
            similarity_result=similarity_result,
            severity=severity,
            context=context,
        )

        recommendations = [
            {
                "type": c.recommendation_type,
                "priority": c.priority,
                "title": c.title,
                "impact": c.impact,
                # Keep payload for backward-compatible API/report consumers.
                "payload": {
                    "title": c.title,
                    "impact": c.impact,
                },
                "signature_hash": c.signature_hash,
            }
            for c in candidates
        ]

        return update_state(state, recommendations=recommendations)
