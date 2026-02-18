"""Conflict matrix module - Multi-dimensional evidence conflict resolution.

This module contains ZERO database access. Pure functions for conflict analysis.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class CounterEvidence:
    """Counter-evidence that reduces fraud risk."""

    evidence_type: str
    strength: float
    description: str
    supporting_data: dict[str, Any]


@dataclass(frozen=True)
class ConflictMatrix:
    """Multi-dimensional conflict analysis.

    Attributes:
        pattern_vs_similarity: Relationship between pattern and similarity scores
        fraud_vs_counter_evidence: Relationship between fraud signals and counter-evidence
        deterministic_vs_llm: Relationship between deterministic and LLM assessments
        overall_conflict_score: 0.0 = no conflict, 1.0 = high conflict
        resolution_strategy: Recommended approach for handling conflicts
    """

    pattern_vs_similarity: str
    fraud_vs_counter_evidence: str
    deterministic_vs_llm: str
    overall_conflict_score: float
    resolution_strategy: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "pattern_vs_similarity": self.pattern_vs_similarity,
            "fraud_vs_counter_evidence": self.fraud_vs_counter_evidence,
            "deterministic_vs_llm": self.deterministic_vs_llm,
            "overall_conflict_score": self.overall_conflict_score,
            "resolution_strategy": self.resolution_strategy,
        }


def compute_conflict_matrix(
    pattern_analysis: dict[str, Any],
    similarity_score: float,
    counter_evidence: list[CounterEvidence],
    llm_reasoning: dict[str, Any] | None = None,
) -> ConflictMatrix:
    """Compute multi-dimensional conflict matrix.

    Args:
        pattern_analysis: Pattern analysis result with severity
        similarity_score: Overall similarity score from similarity engine
        counter_evidence: List of counter-evidence items
        llm_reasoning: Optional LLM reasoning with risk_assessment

    Returns:
        ConflictMatrix with computed scores and resolution strategy
    """
    pattern_severity = pattern_analysis.get("severity", "LOW")
    if isinstance(pattern_severity, str):
        pattern_severity = pattern_severity.upper()
    elif isinstance(pattern_severity, (int, float)):
        pattern_severity = _score_to_severity(pattern_severity)

    pattern_vs_sim = _compute_pattern_similarity_conflict(pattern_severity, similarity_score)

    fraud_vs_counter = _compute_fraud_counter_conflict(
        pattern_severity, similarity_score, counter_evidence
    )

    det_vs_llm = _compute_det_llm_conflict(pattern_severity, llm_reasoning)

    conflict_count = sum(
        [
            pattern_vs_sim == "conflicting",
            fraud_vs_counter == "conflicting",
            det_vs_llm == "conflicting",
        ]
    )
    overall_conflict = conflict_count / 3.0

    resolution = _determine_resolution(
        overall_conflict, fraud_vs_counter, pattern_vs_sim, pattern_severity, counter_evidence
    )

    return ConflictMatrix(
        pattern_vs_similarity=pattern_vs_sim,
        fraud_vs_counter_evidence=fraud_vs_counter,
        deterministic_vs_llm=det_vs_llm,
        overall_conflict_score=overall_conflict,
        resolution_strategy=resolution,
    )


def _score_to_severity(score: float) -> str:
    if score >= 0.8:
        return "CRITICAL"
    elif score >= 0.6:
        return "HIGH"
    elif score >= 0.4:
        return "MEDIUM"
    return "LOW"


def _compute_pattern_similarity_conflict(pattern_severity: str, similarity_score: float) -> str:
    high_pattern = pattern_severity in ("HIGH", "CRITICAL")
    high_similarity = similarity_score > 0.6

    if (high_pattern and high_similarity) or (not high_pattern and similarity_score < 0.3):
        return "aligned"
    elif (high_pattern and similarity_score < 0.3) or (not high_pattern and high_similarity):
        return "conflicting"
    return "neutral"


def _compute_fraud_counter_conflict(
    pattern_severity: str,
    similarity_score: float,
    counter_evidence: list[CounterEvidence],
) -> str:
    fraud_signals = pattern_severity in ("HIGH", "CRITICAL") or similarity_score > 0.5

    if not counter_evidence:
        counter_strength = 0.0
    else:
        counter_strength = sum(ce.strength for ce in counter_evidence) / len(counter_evidence)

    if fraud_signals and counter_strength > 0.5:
        return "conflicting"
    elif not fraud_signals and counter_strength > 0.5:
        return "counter_evidence_dominant"
    elif fraud_signals and counter_strength <= 0.5:
        return "fraud_dominant"
    return "neutral"


def _compute_det_llm_conflict(pattern_severity: str, llm_reasoning: dict[str, Any] | None) -> str:
    if llm_reasoning is None:
        return "neutral"

    llm_risk = llm_reasoning.get("risk_assessment", "MEDIUM")
    if isinstance(llm_risk, str):
        llm_risk = llm_risk.upper()

    det_risk = pattern_severity

    if (llm_risk == "HIGH" and det_risk == "LOW") or (
        llm_risk == "LOW" and det_risk in ("HIGH", "CRITICAL")
    ):
        return "conflicting"
    elif llm_risk == det_risk:
        return "aligned"
    return "neutral"


def _determine_resolution(
    overall_conflict: float,
    fraud_vs_counter: str,
    pattern_vs_sim: str,
    pattern_severity: str,
    counter_evidence: list[CounterEvidence],
) -> str:
    if overall_conflict > 0.6:
        return "flag_for_review"
    if fraud_vs_counter == "counter_evidence_dominant":
        return "trust_counter_evidence"
    if pattern_vs_sim == "conflicting":
        return "weighted_average"
    if counter_evidence and pattern_severity in ("HIGH", "CRITICAL"):
        counter_avg = sum(ce.strength for ce in counter_evidence) / len(counter_evidence)
        if counter_avg > 0.5:
            return "flag_for_review"
    return "trust_deterministic"
