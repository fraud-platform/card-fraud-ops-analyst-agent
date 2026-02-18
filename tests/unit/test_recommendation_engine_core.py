"""Unit tests for recommendation engine core module."""

import pytest

from app.agents.pattern_engine_core import PatternScore
from app.agents.recommendation_engine_core import (
    RecommendationCandidate,
    compute_insight_severity,
    generate_recommendations,
)


def test_generate_recommendations_critical():
    pattern_scores = [
        PatternScore("velocity", 0.9, 0.4, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.3})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="CRITICAL",
        context={},
    )
    assert len(candidates) > 0
    assert any(c.recommendation_type == "review_priority" for c in candidates)


def test_generate_recommendations_velocity_high():
    pattern_scores = [
        PatternScore("velocity", 0.7, 0.4, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.3})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="HIGH",
        context={},
    )
    types = [c.recommendation_type for c in candidates]
    assert "case_action" in types


def test_generate_recommendations_velocity_boundary_inclusive():
    pattern_scores = [
        PatternScore("velocity", 0.6, 0.4, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.3})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="MEDIUM",
        context={},
    )
    types = [c.recommendation_type for c in candidates]
    assert "case_action" in types


def test_generate_recommendations_decline():
    pattern_scores = [
        PatternScore("decline_anomaly", 0.6, 0.3, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.3})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="HIGH",
        context={},
    )
    types = [c.recommendation_type for c in candidates]
    assert "rule_candidate" in types


def test_generate_recommendations_similarity():
    pattern_scores = []
    similarity_result = type("obj", (object,), {"overall_score": 0.6})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="MEDIUM",
        context={},
    )
    types = [c.recommendation_type for c in candidates]
    assert "rule_candidate" in types


def test_generate_recommendations_similarity_boundary_inclusive():
    pattern_scores = []
    similarity_result = type("obj", (object,), {"overall_score": 0.5})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="MEDIUM",
        context={},
    )
    types = [c.recommendation_type for c in candidates]
    assert "rule_candidate" in types


def test_generate_recommendations_amount_anomaly_is_contextual():
    pattern_scores = [
        PatternScore(
            "amount_anomaly",
            0.7,
            0.3,
            {"high_amount": 1500.0},
        ),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.2})()
    context = {
        "transaction": type(
            "Tx",
            (),
            {
                "amount": 1500.0,
                "merchant_id": "merchant-high-risk",
            },
        )(),
    }
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="MEDIUM",
        context=context,
    )
    assert any("amount anomaly" in c.title.lower() for c in candidates)
    assert any("$1500.00" in c.impact for c in candidates)


def test_generate_recommendations_card_testing_escalation():
    pattern_scores = [
        PatternScore(
            "card_testing",
            0.85,
            0.35,
            {"sequence_length": 6, "amount_range": "1.00 - 25.00"},
        ),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.2})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="HIGH",
        context={},
    )
    assert any("card-testing sequence" in c.title.lower() for c in candidates)


def test_generate_recommendations_default():
    pattern_scores = []
    similarity_result = type("obj", (object,), {"overall_score": 0.1})()
    candidates = generate_recommendations(
        pattern_scores=pattern_scores,
        similarity_result=similarity_result,
        severity="LOW",
        context={},
    )
    assert len(candidates) > 0
    assert candidates[0].recommendation_type == "review_priority"


def test_compute_insight_severity_critical():
    pattern_scores = [
        PatternScore("velocity", 0.9, 0.7, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.8})()
    severity = compute_insight_severity(pattern_scores, similarity_result)
    assert severity == "CRITICAL"


def test_compute_insight_severity_high():
    pattern_scores = [
        PatternScore("velocity", 0.6, 0.7, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.5})()
    severity = compute_insight_severity(pattern_scores, similarity_result)
    assert severity == "HIGH"


def test_compute_insight_severity_medium():
    pattern_scores = [
        PatternScore("velocity", 0.4, 0.7, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.2})()
    severity = compute_insight_severity(pattern_scores, similarity_result)
    assert severity == "MEDIUM"


def test_compute_insight_severity_low():
    pattern_scores = [
        PatternScore("velocity", 0.1, 0.7, {}),
    ]
    similarity_result = type("obj", (object,), {"overall_score": 0.1})()
    severity = compute_insight_severity(pattern_scores, similarity_result)
    assert severity == "LOW"


def test_recommendation_candidate_immutable():
    candidate = RecommendationCandidate(
        recommendation_type="rule_candidate",
        priority=1,
        title="Test",
        impact="Impact",
        signature_hash="abc",
    )
    with pytest.raises(AttributeError):
        candidate.priority = 2
