"""Unit tests for conflict matrix module."""

from app.agents.conflict_matrix import (
    ConflictMatrix,
    CounterEvidence,
    _compute_det_llm_conflict,
    _compute_fraud_counter_conflict,
    _compute_pattern_similarity_conflict,
    _determine_resolution,
    _score_to_severity,
    compute_conflict_matrix,
)


class TestScoreToSeverity:
    def test_critical(self):
        assert _score_to_severity(0.9) == "CRITICAL"

    def test_high(self):
        assert _score_to_severity(0.7) == "HIGH"

    def test_medium(self):
        assert _score_to_severity(0.5) == "MEDIUM"

    def test_low(self):
        assert _score_to_severity(0.2) == "LOW"

    def test_boundary_critical(self):
        assert _score_to_severity(0.8) == "CRITICAL"

    def test_boundary_high(self):
        assert _score_to_severity(0.6) == "HIGH"


class TestComputePatternSimilarityConflict:
    def test_high_pattern_high_similarity_aligned(self):
        result = _compute_pattern_similarity_conflict("HIGH", 0.8)
        assert result == "aligned"

    def test_low_pattern_low_similarity_aligned(self):
        result = _compute_pattern_similarity_conflict("LOW", 0.1)
        assert result == "aligned"

    def test_high_pattern_low_similarity_conflicting(self):
        result = _compute_pattern_similarity_conflict("HIGH", 0.1)
        assert result == "conflicting"

    def test_low_pattern_high_similarity_conflicting(self):
        result = _compute_pattern_similarity_conflict("LOW", 0.8)
        assert result == "conflicting"

    def test_critical_pattern_high_similarity_aligned(self):
        result = _compute_pattern_similarity_conflict("CRITICAL", 0.9)
        assert result == "aligned"

    def test_medium_pattern_mid_similarity_neutral(self):
        result = _compute_pattern_similarity_conflict("MEDIUM", 0.5)
        assert result == "neutral"


class TestComputeFraudCounterConflict:
    def test_no_counter_evidence_fraud_dominant(self):
        result = _compute_fraud_counter_conflict("HIGH", 0.8, [])
        assert result == "fraud_dominant"

    def test_strong_counter_evidence_with_fraud_signals_conflicting(self):
        ce = [CounterEvidence("3ds_success", 0.8, "3DS passed", {})]
        result = _compute_fraud_counter_conflict("HIGH", 0.8, ce)
        assert result == "conflicting"

    def test_strong_counter_evidence_no_fraud_signals(self):
        ce = [CounterEvidence("trusted_device", 0.9, "Trusted device", {})]
        result = _compute_fraud_counter_conflict("LOW", 0.2, ce)
        assert result == "counter_evidence_dominant"

    def test_no_fraud_signals_no_counter_evidence_neutral(self):
        result = _compute_fraud_counter_conflict("LOW", 0.1, [])
        assert result == "neutral"

    def test_multiple_counter_evidence_averaged(self):
        ce = [
            CounterEvidence("3ds_success", 0.3, "3DS", {}),
            CounterEvidence("trusted_device", 0.3, "Device", {}),
        ]
        result = _compute_fraud_counter_conflict("HIGH", 0.8, ce)
        # avg strength = 0.3 < 0.5 → fraud_dominant
        assert result == "fraud_dominant"


class TestComputeDetLLMConflict:
    def test_no_llm_reasoning_neutral(self):
        result = _compute_det_llm_conflict("HIGH", None)
        assert result == "neutral"

    def test_high_llm_low_det_conflicting(self):
        result = _compute_det_llm_conflict("LOW", {"risk_assessment": "HIGH"})
        assert result == "conflicting"

    def test_low_llm_high_det_conflicting(self):
        result = _compute_det_llm_conflict("HIGH", {"risk_assessment": "LOW"})
        assert result == "conflicting"

    def test_same_risk_aligned(self):
        result = _compute_det_llm_conflict("HIGH", {"risk_assessment": "HIGH"})
        assert result == "aligned"

    def test_different_but_not_extreme_neutral(self):
        result = _compute_det_llm_conflict("MEDIUM", {"risk_assessment": "HIGH"})
        assert result == "neutral"

    def test_missing_risk_assessment_defaults_medium(self):
        # No risk_assessment key → defaults to "MEDIUM"
        result = _compute_det_llm_conflict("MEDIUM", {})
        assert result == "aligned"


class TestDetermineResolution:
    def test_high_conflict_flag_for_review(self):
        result = _determine_resolution(0.9, "conflicting", "conflicting", "HIGH", [])
        assert result == "flag_for_review"

    def test_counter_evidence_dominant_trust_counter(self):
        result = _determine_resolution(0.1, "counter_evidence_dominant", "aligned", "LOW", [])
        assert result == "trust_counter_evidence"

    def test_pattern_sim_conflict_weighted_average(self):
        result = _determine_resolution(0.2, "fraud_dominant", "conflicting", "MEDIUM", [])
        assert result == "weighted_average"

    def test_no_conflict_trust_deterministic(self):
        result = _determine_resolution(0.0, "fraud_dominant", "aligned", "LOW", [])
        assert result == "trust_deterministic"

    def test_strong_counter_with_high_pattern_flags(self):
        ce = [CounterEvidence("3ds_success", 0.8, "3DS", {})]
        result = _determine_resolution(0.3, "conflicting", "aligned", "HIGH", ce)
        assert result == "flag_for_review"


class TestComputeConflictMatrix:
    def test_returns_conflict_matrix_instance(self):
        result = compute_conflict_matrix(
            pattern_analysis={"severity": "HIGH"},
            similarity_score=0.2,
            counter_evidence=[],
        )
        assert isinstance(result, ConflictMatrix)

    def test_aligned_case_low_conflict(self):
        result = compute_conflict_matrix(
            pattern_analysis={"severity": "HIGH"},
            similarity_score=0.8,
            counter_evidence=[],
        )
        assert result.overall_conflict_score < 0.5

    def test_high_conflict_score(self):
        """High pattern + low similarity + strong counter evidence → high conflict."""
        ce = [CounterEvidence("3ds_success", 0.9, "3DS", {})]
        result = compute_conflict_matrix(
            pattern_analysis={"severity": "HIGH"},
            similarity_score=0.1,
            counter_evidence=ce,
            llm_reasoning={"risk_assessment": "LOW"},
        )
        assert result.overall_conflict_score > 0.5

    def test_to_dict_has_all_keys(self):
        result = compute_conflict_matrix(
            pattern_analysis={"severity": "LOW"},
            similarity_score=0.5,
            counter_evidence=[],
        )
        d = result.to_dict()
        assert "pattern_vs_similarity" in d
        assert "fraud_vs_counter_evidence" in d
        assert "deterministic_vs_llm" in d
        assert "overall_conflict_score" in d
        assert "resolution_strategy" in d

    def test_numeric_severity_converted(self):
        """Numeric severity should be converted to string label."""
        result = compute_conflict_matrix(
            pattern_analysis={"severity": 0.9},  # CRITICAL
            similarity_score=0.8,
            counter_evidence=[],
        )
        assert isinstance(result, ConflictMatrix)

    def test_no_llm_det_vs_llm_neutral(self):
        result = compute_conflict_matrix(
            pattern_analysis={"severity": "MEDIUM"},
            similarity_score=0.5,
            counter_evidence=[],
            llm_reasoning=None,
        )
        assert result.deterministic_vs_llm == "neutral"
