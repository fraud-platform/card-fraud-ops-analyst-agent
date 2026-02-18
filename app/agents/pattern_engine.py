"""Pattern engine - DB-bound module that calls core scoring."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.pattern_engine_core import compute_severity, run_pattern_scoring


class PatternEngine:
    """DB-bound pattern engine that runs pattern scoring."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run pattern analysis on context."""
        pattern_scores = run_pattern_scoring(context)
        severity = compute_severity(pattern_scores)
        patterns = [
            {
                "pattern_name": s.pattern_name,
                "score": s.score,
                "weight": s.weight,
                "details": s.details,
            }
            for s in pattern_scores
        ]

        return {
            "patterns": patterns,
            "pattern_scores": pattern_scores,
            "severity": severity,
        }
