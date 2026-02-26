"""Pattern tool - scores fraud patterns from transaction context."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.core.config import get_settings
from app.core.errors import ToolPreconditionError
from app.tools._core.pattern_logic import (
    compute_severity,
    run_pattern_scoring,
)
from app.tools.base import BaseTool
from app.tools.evidence import EvidenceEntry, append_evidence
from app.utils.dataclass_utils import to_dict_list

if TYPE_CHECKING:
    from app.agent.state import InvestigationState


class PatternTool(BaseTool):
    """Analyze transaction for fraud patterns: velocity bursts, amount anomalies, card testing, cross-merchant spread, time anomalies."""

    @property
    def name(self) -> str:
        return "pattern_tool"

    @property
    def description(self) -> str:
        return "Analyze transaction for fraud patterns: velocity bursts, amount anomalies, card testing, cross-merchant spread, time anomalies"

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        if not context:
            raise ToolPreconditionError(
                "Context must be populated before pattern analysis",
                tool_name=self.name,
            )

        settings = get_settings()
        thresholds = {
            "round_number_thresholds": settings.scoring.amount_round_numbers,
            "amount_high_threshold": settings.scoring.amount_high_threshold,
            "amount_elevated_threshold": settings.scoring.amount_elevated_threshold,
            "amount_zscore_outlier_threshold": settings.scoring.amount_zscore_outlier_threshold,
            "amount_zscore_warning_threshold": settings.scoring.amount_zscore_warning_threshold,
            "velocity_burst_1h_threshold": settings.scoring.velocity_burst_1h_threshold,
            "velocity_burst_6h_threshold": settings.scoring.velocity_burst_6h_threshold,
            "decline_ratio_high_threshold": settings.scoring.decline_ratio_high_threshold,
            "decline_ratio_medium_threshold": settings.scoring.decline_ratio_medium_threshold,
            "cross_merchant_high_threshold": settings.scoring.cross_merchant_high_threshold,
            "cross_merchant_medium_threshold": settings.scoring.cross_merchant_medium_threshold,
            "time_unusual_hours": settings.scoring.time_unusual_hours,
        }

        scores = run_pattern_scoring(context, thresholds)

        pattern_results = {
            "scores": to_dict_list(scores),
            "overall_score": (
                sum(s.score * s.weight for s in scores) / max(sum(s.weight for s in scores), 1)
            ),
            "patterns_detected": [s.pattern_name for s in scores if s.score > 0.5],
        }

        severity = compute_severity(scores)

        evidence_entry = EvidenceEntry(
            category="pattern_analysis",
            tool=self.name,
            description=f"Detected {len(pattern_results['patterns_detected'])} fraud patterns",
            data=pattern_results,
        )

        return append_evidence(
            state,
            evidence_entry,
            pattern_results=pattern_results,
            severity=severity,
        )
