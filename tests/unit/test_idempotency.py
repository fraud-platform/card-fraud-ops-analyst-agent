"""Unit tests for idempotency module."""

from app.utils.idempotency import (
    compute_insight_key,
    compute_recommendation_key,
    compute_rule_draft_key,
)


def test_compute_insight_key():
    key1 = compute_insight_key(
        transaction_id="tx-123",
        evaluation_type="agentic",
        transaction_timestamp="2026-01-01T00:00:00Z",
        insight_type="fraud_analysis",
        model_mode="agentic",
    )
    key2 = compute_insight_key(
        transaction_id="tx-123",
        evaluation_type="agentic",
        transaction_timestamp="2026-01-01T00:00:00Z",
        insight_type="fraud_analysis",
        model_mode="agentic",
    )
    assert key1 == key2
    assert len(key1) == 64


def test_compute_insight_key_different_inputs():
    key1 = compute_insight_key(
        transaction_id="tx-123",
        evaluation_type="agentic",
        transaction_timestamp="2026-01-01T00:00:00Z",
        insight_type="fraud_analysis",
        model_mode="agentic",
    )
    key2 = compute_insight_key(
        transaction_id="tx-456",
        evaluation_type="agentic",
        transaction_timestamp="2026-01-01T00:00:00Z",
        insight_type="fraud_analysis",
        model_mode="agentic",
    )
    assert key1 != key2


def test_compute_recommendation_key():
    key1 = compute_recommendation_key(
        insight_id="insight-123",
        recommendation_type="rule_candidate",
        recommendation_signature_hash="abc123",
    )
    key2 = compute_recommendation_key(
        insight_id="insight-123",
        recommendation_type="rule_candidate",
        recommendation_signature_hash="abc123",
    )
    assert key1 == key2
    assert len(key1) == 64


def test_compute_rule_draft_key():
    key1 = compute_rule_draft_key(
        recommendation_id="rec-123",
        draft_package_version="1.0",
    )
    key2 = compute_rule_draft_key(
        recommendation_id="rec-123",
        draft_package_version="1.0",
    )
    assert key1 == key2
    assert len(key1) == 64
