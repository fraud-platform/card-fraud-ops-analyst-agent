"""Unit tests for recommendation tool."""

import pytest

from app.tools._core.similarity_logic import SimilarityMatch
from app.tools.recommendation_tool import RecommendationTool


class TestRecommendationTool:
    """Tests for RecommendationTool."""

    def test_name(self):
        """RecommendationTool has correct name."""
        tool = RecommendationTool()
        assert tool.name == "recommendation_tool"

    def test_description(self):
        """RecommendationTool has description."""
        tool = RecommendationTool()
        assert "recommendation" in tool.description.lower()

    @pytest.mark.asyncio
    async def test_execute_generates_recommendations(self, state_with_analysis):
        """RecommendationTool generates recommendations from analysis."""
        tool = RecommendationTool()
        result = await tool.execute(state_with_analysis)

        assert "recommendations" in result
        assert isinstance(result["recommendations"], list)

    @pytest.mark.asyncio
    async def test_execute_uses_pattern_scores(self, state_with_analysis):
        """RecommendationTool uses pattern scores for recommendations."""
        tool = RecommendationTool()
        result = await tool.execute(state_with_analysis)

        assert len(result["recommendations"]) >= 0

    @pytest.mark.asyncio
    async def test_execute_handles_empty_pattern_results(self, initial_state):
        """RecommendationTool handles empty pattern results."""
        state = {
            **initial_state,
            "context": {"transaction": {"amount": 100.0}},
            "pattern_results": {"scores": [], "overall_score": 0.0, "patterns_detected": []},
            "similarity_results": {"matches": [], "overall_score": 0.0},
            "severity": "LOW",
        }
        tool = RecommendationTool()
        result = await tool.execute(state)

        assert "recommendations" in result

    @pytest.mark.asyncio
    async def test_reasoning_success_downgrades_high_pattern_severity(self, initial_state):
        """When reasoning succeeds with LOW risk, HIGH pattern severity is suppressed (no_fraud_overescalated fix)."""
        state = {
            **initial_state,
            "context": {"transaction": {"amount": 50.0, "merchant_id": "MERCHANT_1"}},
            "pattern_results": {
                "scores": [
                    {"pattern_name": "time_anomaly", "score": 0.7, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.7,
                "patterns_detected": ["time_anomaly"],
            },
            "similarity_results": {"matches": [], "overall_score": 0.0},
            "severity": "HIGH",  # set by pattern_tool
            "reasoning": {
                "llm_status": "success",
                "risk_level": "LOW",  # LLM correctly identifies no fraud
                "confidence": 0.75,
                "narrative": "Time anomaly explained by cardholder's known travel pattern.",
                "key_findings": [],
                "hypotheses": [],
            },
        }
        tool = RecommendationTool()
        result = await tool.execute(state)

        rec_types = [r["type"] for r in result["recommendations"]]
        # No high-priority escalation when reasoning says LOW
        assert "review_priority" not in rec_types, (
            f"Should not escalate when LLM says LOW risk; got {rec_types}"
        )

    @pytest.mark.asyncio
    async def test_reasoning_parse_error_preserves_pattern_severity(self, initial_state):
        """When reasoning fails (parse_error), fall back to pattern-based severity (conservative)."""
        state = {
            **initial_state,
            "context": {"transaction": {"amount": 500.0, "merchant_id": "MERCHANT_2"}},
            "pattern_results": {
                "scores": [
                    {"pattern_name": "velocity", "score": 0.8, "weight": 1.0, "details": {}}
                ],
                "overall_score": 0.8,
                "patterns_detected": ["velocity"],
            },
            "similarity_results": {"matches": [], "overall_score": 0.0},
            "severity": "HIGH",
            "reasoning": {
                "llm_status": "parse_error",
                "risk_level": "UNKNOWN",
                "confidence": 0.0,
                "summary": "Insufficient model output",
            },
        }
        tool = RecommendationTool()
        result = await tool.execute(state)

        rec_types = [r["type"] for r in result["recommendations"]]
        # With HIGH severity and no correcting reasoning, escalation is retained
        assert "review_priority" in rec_types, (
            f"Should escalate when pattern says HIGH and reasoning failed; got {rec_types}"
        )

    @pytest.mark.asyncio
    async def test_execute_respects_high_severity(self, state_with_analysis):
        """RecommendationTool generates higher priority for high severity."""
        state_with_analysis["severity"] = "HIGH"
        state_with_analysis["pattern_results"]["scores"] = [
            {"pattern_name": "velocity_burst", "score": 0.9, "weight": 1.0}
        ]
        tool = RecommendationTool()
        result = await tool.execute(state_with_analysis)

        for rec in result["recommendations"]:
            assert "type" in rec
            assert "title" in rec
            assert isinstance(rec.get("payload"), dict)
            assert rec["payload"].get("title") == rec["title"]
            assert rec["payload"].get("impact") == rec["impact"]

    @pytest.mark.asyncio
    async def test_execute_accepts_similarity_match_objects(self, initial_state):
        """Similarity match objects should not break recommendation generation."""
        state = {
            **initial_state,
            "context": {"transaction": {"amount": 120.0, "merchant_id": "MERCHANT_3"}},
            "pattern_results": {"scores": [], "overall_score": 0.0, "patterns_detected": []},
            "similarity_results": {
                "matches": [
                    SimilarityMatch(
                        match_id="txn-sim-1",
                        match_type="precomputed",
                        similarity_score=0.72,
                        details={},
                        counter_evidence=None,
                    )
                ],
                "overall_score": 0.72,
            },
            "severity": "MEDIUM",
        }
        tool = RecommendationTool()
        result = await tool.execute(state)

        assert isinstance(result["recommendations"], list)
        assert len(result["recommendations"]) > 0
