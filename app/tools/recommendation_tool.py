"""Recommendation tool - generates fraud investigation recommendations."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.agent.state import update_state
from app.tools._core.pattern_logic import PatternScore
from app.tools._core.recommendation_logic import generate_recommendations
from app.tools._core.similarity_logic import SimilarityMatch, SimilarityResult
from app.tools.base import BaseTool

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
        context = state["context"]
        pattern_results = state["pattern_results"]
        similarity_results = state["similarity_results"]
        reasoning = state.get("reasoning") or {}
        severity = state["severity"]

        # When reasoning succeeded, trust its risk_level to override severity in both
        # directions (fixes no_fraud_overescalated: pattern HIGH + LLM LOW → LOW recs).
        # When reasoning failed/unavailable, only allow an upgrade (preserve existing caution).
        reasoning_status = reasoning.get("llm_status") if isinstance(reasoning, dict) else None
        reasoning_risk = reasoning.get("risk_level") if isinstance(reasoning, dict) else None
        if reasoning_status == "success" and reasoning_risk in (
            "CRITICAL",
            "HIGH",
            "MEDIUM",
            "LOW",
        ):
            severity = reasoning_risk
        else:
            reasoning_severity = reasoning.get("severity") if isinstance(reasoning, dict) else None
            if reasoning_severity and reasoning_severity in ("CRITICAL", "HIGH", "MEDIUM", "LOW"):
                severity_rank = {"CRITICAL": 4, "HIGH": 3, "MEDIUM": 2, "LOW": 1}
                if severity_rank.get(reasoning_severity, 0) > severity_rank.get(severity, 0):
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

        def _item_value(item: object, key: str, default: object = None) -> object:
            if isinstance(item, dict):
                return item.get(key, default)
            return getattr(item, key, default)

        matches = [
            SimilarityMatch(
                match_id=str(_item_value(m, "match_id") or _item_value(m, "transaction_id", "")),
                match_type=str(_item_value(m, "match_type", "unknown")),
                similarity_score=float(
                    _item_value(m, "similarity_score") or _item_value(m, "score", 0.0)
                ),
                details=(
                    _item_value(m, "details", {})
                    if isinstance(_item_value(m, "details", {}), dict)
                    else {}
                ),
                counter_evidence=(
                    _item_value(m, "counter_evidence")
                    if isinstance(_item_value(m, "counter_evidence"), list)
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
