"""Unit tests for explanation builder module."""

import pytest

from app.agents.explanation_builder import Explanation, ExplanationBuilder, ExplanationSection


@pytest.fixture()
def builder() -> ExplanationBuilder:
    return ExplanationBuilder()


@pytest.fixture()
def base_context() -> dict:
    return {"investigation_id": "inv-123", "transaction_id": "tx-456"}


@pytest.fixture()
def pattern_analysis_with_patterns() -> dict:
    return {
        "severity": "HIGH",
        "patterns": [
            {"pattern_name": "velocity_spike", "score": 0.85, "description": "High velocity"},
            {"pattern_name": "card_testing", "score": 0.65, "description": "Card test pattern"},
        ],
    }


@pytest.fixture()
def similarity_result_with_matches() -> dict:
    return {
        "overall_score": 0.75,
        "matches": [
            {
                "match_id": "tx-abc",
                "match_type": "vector",
                "similarity_score": 0.9,
                "counter_evidence": [
                    {"type": "3ds_success", "strength": 0.8, "description": "3DS passed"}
                ],
            }
        ],
    }


class TestExplanationBuilderBuild:
    def test_returns_explanation_instance(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        assert isinstance(result, Explanation)

    def test_investigation_id_set(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        assert result.investigation_id == "inv-123"

    def test_transaction_id_set(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        assert result.transaction_id == "tx-456"

    def test_has_six_sections(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "MEDIUM", "patterns": []},
            similarity_result={"overall_score": 0.5, "matches": []},
            conflict_matrix=None,
        )
        assert len(result.sections) == 6

    def test_sections_are_explanation_section_instances(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        for section in result.sections:
            assert isinstance(section, ExplanationSection)

    def test_metadata_model_mode_deterministic_without_llm(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
            llm_reasoning=None,
        )
        assert result.metadata["model_mode"] == "deterministic"

    def test_metadata_model_mode_hybrid_with_llm(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result={"overall_score": 0.8, "matches": []},
            conflict_matrix=None,
            llm_reasoning={"narrative_summary": "High risk", "confidence": 0.9},
        )
        assert result.metadata["model_mode"] == "hybrid"

    def test_llm_summary_in_executive_section(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
            llm_reasoning={"narrative_summary": "Fraud suspected", "confidence": 0.8},
        )
        exec_section = next(s for s in result.sections if s.title == "Executive Summary")
        assert "Fraud suspected" in exec_section.content


class TestToMarkdown:
    def test_returns_string(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        md = result.to_markdown()
        assert isinstance(md, str)

    def test_contains_header(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        md = result.to_markdown()
        assert "# Investigation Report" in md

    def test_contains_transaction_id(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        md = result.to_markdown()
        assert "tx-456" in md

    def test_sections_ordered_by_priority(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        md = result.to_markdown()
        exec_pos = md.index("Executive Summary")
        pattern_pos = md.index("Pattern Analysis")
        assert exec_pos < pattern_pos


class TestPatternSection:
    def test_no_patterns_shows_no_significant_patterns(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        pattern_section = next(s for s in result.sections if s.title == "Pattern Analysis")
        assert "No significant patterns" in pattern_section.content

    def test_patterns_listed_by_score(
        self,
        builder: ExplanationBuilder,
        base_context: dict,
        pattern_analysis_with_patterns: dict,
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis=pattern_analysis_with_patterns,
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        pattern_section = next(s for s in result.sections if s.title == "Pattern Analysis")
        velocity_pos = pattern_section.content.index("velocity_spike")
        card_pos = pattern_section.content.index("card_testing")
        assert velocity_pos < card_pos  # Higher score listed first


class TestSimilaritySection:
    def test_no_matches_shows_zero(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        sim_section = next(s for s in result.sections if s.title == "Similarity Analysis")
        assert "0" in sim_section.content

    def test_match_id_in_section(
        self,
        builder: ExplanationBuilder,
        base_context: dict,
        similarity_result_with_matches: dict,
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result=similarity_result_with_matches,
            conflict_matrix=None,
        )
        sim_section = next(s for s in result.sections if s.title == "Similarity Analysis")
        assert "tx-abc" in sim_section.content


class TestCounterEvidenceSection:
    def test_no_counter_evidence(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        ce_section = next(s for s in result.sections if s.title == "Counter-Evidence")
        assert "No counter-evidence" in ce_section.content

    def test_counter_evidence_listed(
        self,
        builder: ExplanationBuilder,
        base_context: dict,
        similarity_result_with_matches: dict,
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result=similarity_result_with_matches,
            conflict_matrix=None,
        )
        ce_section = next(s for s in result.sections if s.title == "Counter-Evidence")
        assert "3ds_success" in ce_section.content


class TestConflictSection:
    def test_no_conflict_matrix(self, builder: ExplanationBuilder, base_context: dict):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix=None,
        )
        conflict_section = next(s for s in result.sections if s.title == "Conflict Resolution")
        assert "No conflict analysis" in conflict_section.content

    def test_low_conflict_score_no_conflicts_message(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "LOW", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix={"overall_conflict_score": 0.1, "resolution_strategy": "trust_det"},
        )
        conflict_section = next(s for s in result.sections if s.title == "Conflict Resolution")
        assert "No significant conflicts" in conflict_section.content

    def test_high_conflict_score_shows_details(
        self, builder: ExplanationBuilder, base_context: dict
    ):
        result = builder.build(
            context=base_context,
            pattern_analysis={"severity": "HIGH", "patterns": []},
            similarity_result={"overall_score": 0.0, "matches": []},
            conflict_matrix={
                "overall_conflict_score": 0.8,
                "resolution_strategy": "flag_for_review",
                "pattern_vs_similarity": "conflicting",
                "fraud_vs_counter_evidence": "conflicting",
                "deterministic_vs_llm": "neutral",
            },
        )
        conflict_section = next(s for s in result.sections if s.title == "Conflict Resolution")
        assert "0.80" in conflict_section.content or "0.8" in conflict_section.content
