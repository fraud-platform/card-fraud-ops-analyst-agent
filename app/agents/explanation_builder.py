"""Explanation builder - Generate human-readable analysis explanations.

This module contains ZERO database access. Pure functions for generating explanations.
"""

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any


@dataclass(frozen=True)
class ExplanationSection:
    """Single section of explanation."""

    title: str
    content: str
    priority: int


@dataclass(frozen=True)
class Explanation:
    """Full explanation with sections."""

    investigation_id: str
    transaction_id: str
    sections: list[ExplanationSection]
    metadata: dict[str, Any]
    generated_at: datetime

    def to_markdown(self) -> str:
        """Render explanation as markdown document."""
        lines = [
            "# Investigation Report",
            f"**Transaction ID:** {self.transaction_id}",
            f"**Generated:** {self.generated_at.isoformat()}",
            "",
        ]

        for section in sorted(self.sections, key=lambda s: s.priority):
            lines.append(f"## {section.title}")
            lines.append(section.content)
            lines.append("")

        return "\n".join(lines)


class ExplanationBuilder:
    """Generate human-readable explanations from analysis results."""

    def build(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_result: dict[str, Any],
        conflict_matrix: dict[str, Any] | None,
        llm_reasoning: dict[str, Any] | None = None,
    ) -> Explanation:
        """Build full explanation with sections.

        Args:
            context: Investigation context with transaction_id, investigation_id
            pattern_analysis: Pattern analysis results
            similarity_result: Similarity analysis results
            conflict_matrix: Optional conflict matrix
            llm_reasoning: Optional LLM reasoning

        Returns:
            Explanation with sections
        """
        sections = []

        sections.append(self._executive_summary(context, llm_reasoning, pattern_analysis))
        sections.append(self._pattern_analysis(pattern_analysis))
        sections.append(self._similarity_analysis(similarity_result))
        sections.append(self._counter_evidence(similarity_result))
        sections.append(self._conflict_resolution(conflict_matrix))
        sections.append(self._recommended_actions(context, conflict_matrix))

        return Explanation(
            investigation_id=context.get("investigation_id", ""),
            transaction_id=context.get("transaction_id", ""),
            sections=sections,
            metadata={
                "model_mode": "hybrid" if llm_reasoning else "deterministic",
                "llm_confidence": llm_reasoning.get("confidence") if llm_reasoning else None,
            },
            generated_at=datetime.now(UTC),
        )

    def _executive_summary(
        self,
        context: dict[str, Any],
        llm_reasoning: dict[str, Any] | None,
        pattern_analysis: dict[str, Any],
    ) -> ExplanationSection:
        """Build executive summary section."""
        if llm_reasoning:
            summary = llm_reasoning.get("narrative_summary", "")
            risk = llm_reasoning.get("risk_assessment", "UNKNOWN")
        else:
            severity = pattern_analysis.get("severity", "UNKNOWN")
            summary = self._deterministic_summary(context, pattern_analysis)
            risk = severity

        return ExplanationSection(
            title="Executive Summary",
            content=f"{summary}\n\n**Risk Level:** {risk}",
            priority=1,
        )

    def _deterministic_summary(
        self, context: dict[str, Any], pattern_analysis: dict[str, Any]
    ) -> str:
        """Generate deterministic summary when no LLM available."""
        severity = pattern_analysis.get("severity", "UNKNOWN")
        patterns = pattern_analysis.get("patterns", [])

        if not patterns:
            return f"Transaction analysis completed with {severity} risk assessment."

        top_pattern = max(patterns, key=lambda p: p.get("score", 0))
        pattern_name = top_pattern.get("pattern_name", "unknown")

        return f"Analysis identified {len(patterns)} patterns with {severity} risk. Primary pattern: {pattern_name}."

    def _pattern_analysis(self, pattern_analysis: dict[str, Any]) -> ExplanationSection:
        """Build pattern analysis section."""
        patterns = pattern_analysis.get("patterns", [])

        if not patterns:
            return ExplanationSection(
                title="Pattern Analysis",
                content="No significant patterns detected.",
                priority=2,
            )

        lines = ["### Detected Patterns\n"]

        for pattern in sorted(patterns, key=lambda p: p.get("score", 0), reverse=True):
            score = pattern.get("score", 0)
            name = pattern.get("pattern_name", "unknown")
            description = pattern.get("description", "")

            lines.append(f"**{name}** (Score: {score:.2f})")
            lines.append(f"- {description}")
            lines.append("")

        return ExplanationSection(
            title="Pattern Analysis",
            content="\n".join(lines),
            priority=2,
        )

    def _similarity_analysis(self, similarity_result: dict[str, Any]) -> ExplanationSection:
        """Build similarity analysis section."""
        matches = similarity_result.get("matches", [])
        overall = similarity_result.get("overall_score", 0.0)

        lines = [
            f"### Similarity Score: {overall:.2f}\n",
            f"Found **{len(matches)}** similar transactions.\n",
        ]

        for match in matches[:5]:
            lines.append(f"- Transaction `{match.get('match_id', 'unknown')}`")
            lines.append(f"  - Similarity: {match.get('similarity_score', 0):.2f}")
            lines.append(f"  - Type: {match.get('match_type', 'unknown')}")

            ce = match.get("counter_evidence")
            if ce:
                lines.append("  - Counter-Evidence:")
                for item in ce:
                    lines.append(f"    - {item.get('description', '')}")

        return ExplanationSection(
            title="Similarity Analysis",
            content="\n".join(lines),
            priority=3,
        )

    def _counter_evidence(self, similarity_result: dict[str, Any]) -> ExplanationSection:
        """Build counter-evidence section."""
        matches = similarity_result.get("matches", [])
        all_counter_evidence = []

        for match in matches:
            ce = match.get("counter_evidence")
            if ce:
                all_counter_evidence.extend(ce)

        if not all_counter_evidence:
            return ExplanationSection(
                title="Counter-Evidence",
                content="No counter-evidence detected.",
                priority=4,
            )

        lines = ["### Evidence Reducing Fraud Risk\n"]

        for ce in all_counter_evidence:
            ce_type = ce.get("type", "unknown")
            strength = ce.get("strength", 0)
            description = ce.get("description", "")
            lines.append(f"- **{ce_type}** (Strength: {strength:.2f})")
            lines.append(f"  - {description}")
            lines.append("")

        return ExplanationSection(
            title="Counter-Evidence",
            content="\n".join(lines),
            priority=4,
        )

    def _conflict_resolution(self, conflict_matrix: dict[str, Any] | None) -> ExplanationSection:
        """Build conflict resolution section."""
        if conflict_matrix is None:
            return ExplanationSection(
                title="Conflict Resolution",
                content="No conflict analysis available.",
                priority=5,
            )

        overall = conflict_matrix.get("overall_conflict_score", 0.0)

        if overall < 0.3:
            return ExplanationSection(
                title="Conflict Resolution",
                content="No significant conflicts detected between evidence types.",
                priority=5,
            )

        lines = [
            f"### Conflict Score: {overall:.2f}\n",
            f"**Resolution Strategy:** {conflict_matrix.get('resolution_strategy', 'unknown')}\n",
            "**Conflicts Detected:**\n",
        ]

        pvs = conflict_matrix.get("pattern_vs_similarity", "neutral")
        fvs = conflict_matrix.get("fraud_vs_counter_evidence", "neutral")
        dvl = conflict_matrix.get("deterministic_vs_llm", "neutral")

        if pvs == "conflicting":
            lines.append("- Pattern analysis conflicts with similarity results")

        if fvs == "conflicting":
            lines.append("- Fraud signals conflict with counter-evidence")

        if dvl == "conflicting":
            lines.append("- Deterministic analysis conflicts with LLM assessment")

        return ExplanationSection(
            title="Conflict Resolution",
            content="\n".join(lines),
            priority=5,
        )

    def _recommended_actions(
        self, context: dict[str, Any], conflict_matrix: dict[str, Any] | None
    ) -> ExplanationSection:
        """Build recommended actions section."""
        lines = ["### Recommended Actions\n"]

        if conflict_matrix:
            strategy = conflict_matrix.get("resolution_strategy", "unknown")

            if strategy == "flag_for_review":
                lines.append("1. **Flag for human review** due to conflicting evidence")
                lines.append("2. Prioritize review based on conflict score")
            elif strategy == "trust_counter_evidence":
                lines.append("1. Consider downgrading risk level")
                lines.append("2. Monitor for additional evidence")
            elif strategy == "trust_deterministic":
                lines.append("1. Proceed with standard fraud review process")
            else:
                lines.append("1. Review based on analysis results")
        else:
            lines.append("1. Proceed with standard fraud review process")

        return ExplanationSection(
            title="Recommended Actions",
            content="\n".join(lines),
            priority=6,
        )
