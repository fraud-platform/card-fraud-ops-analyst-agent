"""Unit tests for new schemas: conflicts, evidence, explanations."""

from datetime import UTC, datetime

from app.schemas.v1.conflicts import ConflictMatrixResponse
from app.schemas.v1.evidence import EvidenceCreateRequest, EvidenceEnvelope
from app.schemas.v1.explanations import (
    ExplanationMetadata,
    ExplanationResponse,
    ExplanationSection,
)


class TestConflictMatrixResponse:
    def test_instantiation(self):
        obj = ConflictMatrixResponse(
            pattern_vs_similarity="aligned",
            fraud_vs_counter_evidence="fraud_dominant",
            deterministic_vs_llm="neutral",
            overall_conflict_score=0.2,
            resolution_strategy="trust_deterministic",
        )
        assert obj.overall_conflict_score == 0.2
        assert obj.resolution_strategy == "trust_deterministic"

    def test_from_dict(self):
        data = {
            "pattern_vs_similarity": "conflicting",
            "fraud_vs_counter_evidence": "conflicting",
            "deterministic_vs_llm": "conflicting",
            "overall_conflict_score": 1.0,
            "resolution_strategy": "flag_for_review",
        }
        obj = ConflictMatrixResponse(**data)
        assert obj.pattern_vs_similarity == "conflicting"


class TestEvidenceEnvelope:
    def test_instantiation_minimal(self):
        obj = EvidenceEnvelope(
            evidence_id="ev-1",
            evidence_kind="pattern",
            category="velocity",
            strength=0.8,
            description="High velocity",
            supporting_data={"count": 5},
            timestamp=datetime.now(UTC),
            freshness_weight=0.9,
        )
        assert obj.evidence_kind == "pattern"
        assert obj.related_transaction_ids == []
        assert obj.evidence_references == {}

    def test_with_related_txns(self):
        obj = EvidenceEnvelope(
            evidence_id="ev-2",
            evidence_kind="similarity",
            category="vector",
            strength=0.75,
            description="Similar tx",
            supporting_data={},
            timestamp=datetime.now(UTC),
            freshness_weight=0.7,
            related_transaction_ids=["tx-a", "tx-b"],
        )
        assert len(obj.related_transaction_ids) == 2


class TestEvidenceCreateRequest:
    def test_instantiation_minimal(self):
        req = EvidenceCreateRequest(
            evidence_kind="counter_evidence",
            category="3ds_success",
            strength=0.85,
            description="3DS authenticated",
            supporting_data={},
        )
        assert req.evidence_kind == "counter_evidence"
        assert req.related_transaction_ids == []

    def test_with_all_fields(self):
        req = EvidenceCreateRequest(
            evidence_kind="pattern",
            category="velocity",
            strength=0.6,
            description="Velocity spike",
            supporting_data={"count": 10},
            related_transaction_ids=["tx-x"],
            evidence_references={"ref": "value"},
        )
        assert req.evidence_references == {"ref": "value"}


class TestExplanationSection:
    def test_instantiation(self):
        section = ExplanationSection(title="Executive Summary", content="High risk", priority=1)
        assert section.title == "Executive Summary"
        assert section.priority == 1


class TestExplanationMetadata:
    def test_without_confidence(self):
        meta = ExplanationMetadata(model_mode="deterministic")
        assert meta.llm_confidence is None

    def test_with_confidence(self):
        meta = ExplanationMetadata(model_mode="hybrid", llm_confidence=0.88)
        assert meta.llm_confidence == 0.88


class TestExplanationResponse:
    def test_instantiation(self):
        now = datetime.now(UTC)
        resp = ExplanationResponse(
            investigation_id="inv-1",
            transaction_id="tx-1",
            sections=[ExplanationSection(title="Summary", content="ok", priority=1)],
            markdown="# Report\n## Summary\nok",
            metadata=ExplanationMetadata(model_mode="deterministic"),
            generated_at=now,
        )
        assert resp.investigation_id == "inv-1"
        assert len(resp.sections) == 1
