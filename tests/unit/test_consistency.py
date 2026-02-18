"""Unit tests for LLM/deterministic consistency checks."""

from app.llm.consistency import check_consistency


def test_consistency_passes_on_aligned_inputs():
    result = check_consistency(
        llm_response={
            "risk_assessment": "HIGH",
            "key_findings": ["velocity score 0.9"],
            "confidence": 0.7,
        },
        deterministic_evidence={
            "severity": "HIGH",
            "evidence": [{"pattern_name": "velocity", "score": 0.9}],
            "pattern_scores": [{"score": 0.9}],
        },
    )
    assert result.passed is True
    assert result.score >= 0.7


def test_consistency_fails_on_severity_mismatch():
    result = check_consistency(
        llm_response={"risk_assessment": "LOW", "key_findings": [], "confidence": 0.9},
        deterministic_evidence={"severity": "CRITICAL", "evidence": [], "pattern_scores": []},
        threshold=0.8,
    )
    assert result.passed is False
    assert any("Severity mismatch" in v for v in result.violations)
