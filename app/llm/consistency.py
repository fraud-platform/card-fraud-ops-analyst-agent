"""Consistency checks between LLM response and deterministic evidence."""

from dataclasses import dataclass
from typing import Any


@dataclass
class ConsistencyResult:
    """Result of consistency check."""

    passed: bool
    violations: list[str]
    score: float


SEVERITY_ORDER = {"LOW": 0, "MEDIUM": 1, "HIGH": 2, "CRITICAL": 3}


def check_consistency(
    llm_response: dict[str, Any],
    deterministic_evidence: dict[str, Any],
    threshold: float = 0.7,
) -> ConsistencyResult:
    """Check LLM response consistency with deterministic evidence.

    Args:
        llm_response: Parsed LLM response dict
        deterministic_evidence: Deterministic analysis results
        threshold: Minimum score to pass (0.0-1.0)

    Returns:
        ConsistencyResult with pass/fail status and details
    """
    violations: list[str] = []
    score = 1.0

    llm_severity = llm_response.get("risk_assessment", "").upper()
    det_severity = deterministic_evidence.get("severity", "").upper()

    if llm_severity and det_severity:
        llm_level = SEVERITY_ORDER.get(llm_severity, 2)
        det_level = SEVERITY_ORDER.get(det_severity, 2)

        if abs(llm_level - det_level) > 1:
            violations.append(
                f"Severity mismatch: LLM={llm_severity}, Deterministic={det_severity}"
            )
            score -= 0.3

    key_findings = llm_response.get("key_findings", [])
    if key_findings and isinstance(key_findings, list):
        evidence_items = deterministic_evidence.get("evidence", [])
        if evidence_items:
            grounding = _check_evidence_grounding(key_findings, evidence_items)
            if grounding < threshold:
                violations.append(
                    f"Evidence grounding below threshold: {grounding:.2f} < {threshold}"
                )
                score -= 0.3

    llm_confidence = llm_response.get("confidence")
    if llm_confidence is not None:
        pattern_scores = deterministic_evidence.get("pattern_scores", [])
        if pattern_scores:
            avg_score = sum(s.get("score", 0) for s in pattern_scores) / len(pattern_scores)
            if llm_confidence > 0.8 and avg_score < 0.5:
                violations.append(
                    f"Confidence not calibrated: LLM={llm_confidence}, Patterns={avg_score:.2f}"
                )
                score -= 0.2

    score = max(0.0, min(1.0, score))

    return ConsistencyResult(
        passed=score >= threshold,
        violations=violations,
        score=score,
    )


def _check_evidence_grounding(
    key_findings: list[str],
    evidence_items: list[dict[str, Any]],
) -> float:
    """Check what fraction of findings reference actual evidence.

    Args:
        key_findings: List of findings from LLM
        evidence_items: List of evidence items

    Returns:
        Grounding score (0.0-1.0)
    """
    if not key_findings:
        return 1.0

    evidence_texts = []
    for item in evidence_items:
        pattern = item.get("pattern_name", "")
        score = item.get("score", 0)
        evidence_texts.append(f"{pattern} score {score}")

    findings_text = " ".join(key_findings).lower()

    grounded_count = 0
    for evidence in evidence_texts:
        if any(word in findings_text for word in evidence.lower().split()):
            grounded_count += 1

    return grounded_count / len(key_findings)
