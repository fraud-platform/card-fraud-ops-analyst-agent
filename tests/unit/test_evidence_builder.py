"""Unit tests for evidence builder module."""

from datetime import UTC, datetime

import pytest

from app.agents.evidence_builder import EvidenceBuilder, EvidenceEnvelope


@pytest.fixture()
def builder() -> EvidenceBuilder:
    return EvidenceBuilder()


class TestBuildPatternEvidence:
    def test_returns_evidence_envelope(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="velocity_spike",
            score=0.75,
            description="High velocity detected",
            supporting_data={"count": 10},
        )
        assert isinstance(ev, EvidenceEnvelope)

    def test_evidence_kind_is_pattern(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="card_testing",
            score=0.5,
            description="Card testing pattern",
            supporting_data={},
        )
        assert ev.evidence_kind == "pattern"

    def test_category_is_pattern_name(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="cross_merchant",
            score=0.6,
            description="Cross-merchant bust-out",
            supporting_data={},
        )
        assert ev.category == "cross_merchant"

    def test_strength_is_score(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="velocity",
            score=0.9,
            description="test",
            supporting_data={},
        )
        assert ev.strength == 0.9

    def test_related_txns_from_supporting_data(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="velocity",
            score=0.5,
            description="test",
            supporting_data={"related_transaction_ids": ["tx-1", "tx-2"]},
        )
        assert "tx-1" in ev.related_transaction_ids

    def test_freshness_weight_between_0_and_1(self, builder: EvidenceBuilder):
        ts = datetime.now(UTC)
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="velocity",
            score=0.5,
            description="test",
            supporting_data={},
            transaction_timestamp=ts,
        )
        assert 0.0 <= ev.freshness_weight <= 1.0

    def test_to_jsonb_has_required_keys(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="velocity",
            score=0.5,
            description="test",
            supporting_data={},
        )
        d = ev.to_jsonb()
        for key in ("evidence_id", "evidence_kind", "category", "strength", "description"):
            assert key in d


class TestBuildSimilarityEvidence:
    def test_evidence_kind_is_similarity(self, builder: EvidenceBuilder):
        match = {"match_id": "tx-abc", "match_type": "vector", "similarity_score": 0.85}
        ev = builder.build_similarity_evidence(investigation_id="inv-1", match=match)
        assert ev.evidence_kind == "similarity"

    def test_strength_from_similarity_score(self, builder: EvidenceBuilder):
        match = {"match_id": "tx-abc", "match_type": "vector", "similarity_score": 0.85}
        ev = builder.build_similarity_evidence(investigation_id="inv-1", match=match)
        assert ev.strength == 0.85

    def test_category_from_match_type(self, builder: EvidenceBuilder):
        match = {"match_id": "tx-abc", "match_type": "attribute", "similarity_score": 0.5}
        ev = builder.build_similarity_evidence(investigation_id="inv-1", match=match)
        assert ev.category == "attribute"

    def test_related_txns_includes_match_id(self, builder: EvidenceBuilder):
        match = {"match_id": "tx-xyz", "similarity_score": 0.7}
        ev = builder.build_similarity_evidence(investigation_id="inv-1", match=match)
        assert "tx-xyz" in ev.related_transaction_ids

    def test_missing_similarity_score_defaults_zero(self, builder: EvidenceBuilder):
        match = {"match_id": "tx-abc", "match_type": "vector"}
        ev = builder.build_similarity_evidence(investigation_id="inv-1", match=match)
        assert ev.strength == 0.0


class TestBuildCounterEvidence:
    def test_evidence_kind_is_counter_evidence(self, builder: EvidenceBuilder):
        ev = builder.build_counter_evidence(
            investigation_id="inv-1",
            evidence_type="3ds_success",
            strength=0.8,
            description="3DS authenticated",
            supporting_data={},
        )
        assert ev.evidence_kind == "counter_evidence"

    def test_category_from_evidence_type(self, builder: EvidenceBuilder):
        ev = builder.build_counter_evidence(
            investigation_id="inv-1",
            evidence_type="trusted_device",
            strength=0.7,
            description="Trusted device",
            supporting_data={},
        )
        assert ev.category == "trusted_device"

    def test_strength_stored_correctly(self, builder: EvidenceBuilder):
        ev = builder.build_counter_evidence(
            investigation_id="inv-1",
            evidence_type="3ds_success",
            strength=0.9,
            description="test",
            supporting_data={},
        )
        assert ev.strength == 0.9

    def test_related_txns_from_supporting_data(self, builder: EvidenceBuilder):
        ev = builder.build_counter_evidence(
            investigation_id="inv-1",
            evidence_type="3ds_success",
            strength=0.8,
            description="test",
            supporting_data={"transaction_ids": ["tx-a", "tx-b"]},
        )
        assert "tx-a" in ev.related_transaction_ids


class TestBuildConflictEvidence:
    def test_evidence_kind_is_conflict(self, builder: EvidenceBuilder):
        ev = builder.build_conflict_evidence(
            investigation_id="inv-1",
            conflict_matrix={
                "overall_conflict_score": 0.6,
                "resolution_strategy": "flag_for_review",
            },
        )
        assert ev.evidence_kind == "conflict"

    def test_strength_from_conflict_score(self, builder: EvidenceBuilder):
        ev = builder.build_conflict_evidence(
            investigation_id="inv-1",
            conflict_matrix={"overall_conflict_score": 0.4, "resolution_strategy": "weighted"},
        )
        assert ev.strength == 0.4

    def test_freshness_weight_is_1_for_conflict(self, builder: EvidenceBuilder):
        ev = builder.build_conflict_evidence(
            investigation_id="inv-1",
            conflict_matrix={"overall_conflict_score": 0.3},
        )
        assert ev.freshness_weight == 1.0


class TestBuildLLMReasoningEvidence:
    def test_evidence_kind_is_llm_reasoning(self, builder: EvidenceBuilder):
        ev = builder.build_llm_reasoning_evidence(
            investigation_id="inv-1",
            llm_reasoning={"confidence": 0.85, "narrative_summary": "High risk"},
        )
        assert ev.evidence_kind == "llm_reasoning"

    def test_strength_from_confidence(self, builder: EvidenceBuilder):
        ev = builder.build_llm_reasoning_evidence(
            investigation_id="inv-1",
            llm_reasoning={"confidence": 0.9},
        )
        assert ev.strength == 0.9

    def test_missing_confidence_defaults_0_5(self, builder: EvidenceBuilder):
        ev = builder.build_llm_reasoning_evidence(
            investigation_id="inv-1",
            llm_reasoning={},
        )
        assert ev.strength == 0.5

    def test_description_from_narrative_summary(self, builder: EvidenceBuilder):
        ev = builder.build_llm_reasoning_evidence(
            investigation_id="inv-1",
            llm_reasoning={"confidence": 0.7, "narrative_summary": "Card testing detected"},
        )
        assert "Card testing" in ev.description


class TestEvidenceEnvelopeToJsonb:
    def test_jsonb_timestamp_is_string(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="test",
            score=0.5,
            description="test",
            supporting_data={},
        )
        d = ev.to_jsonb()
        assert isinstance(d["timestamp"], str)

    def test_jsonb_all_required_keys(self, builder: EvidenceBuilder):
        ev = builder.build_pattern_evidence(
            investigation_id="inv-1",
            pattern_name="test",
            score=0.5,
            description="test",
            supporting_data={},
        )
        d = ev.to_jsonb()
        expected_keys = {
            "evidence_id",
            "evidence_kind",
            "category",
            "strength",
            "description",
            "supporting_data",
            "timestamp",
            "freshness_weight",
            "related_transaction_ids",
            "evidence_references",
        }
        assert expected_keys.issubset(d.keys())
