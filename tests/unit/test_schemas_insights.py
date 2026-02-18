"""Unit tests for insights schemas."""

from datetime import datetime

from app.schemas.v1.insights import (
    EvidenceItem,
    InsightDetail,
    InsightListResponse,
)


def test_evidence_item():
    item = EvidenceItem(
        evidence_id="ev-123",
        evidence_kind="transaction_data",
        evidence_payload={"amount": 100.0},
        created_at=datetime.now(),
    )
    assert item.evidence_id == "ev-123"
    assert item.evidence_kind == "transaction_data"


def test_insight_detail():
    detail = InsightDetail(
        insight_id="ins-123",
        transaction_id="tx-123",
        severity="HIGH",
        summary="Test insight",
        insight_type="fraud_analysis",
        model_mode="deterministic",
        generated_at=datetime.now(),
    )
    assert detail.insight_id == "ins-123"
    assert len(detail.evidence) == 0


def test_insight_list_response():
    response = InsightListResponse(
        insights=[],
    )
    assert response.next_cursor is None
    assert response.insights == []
