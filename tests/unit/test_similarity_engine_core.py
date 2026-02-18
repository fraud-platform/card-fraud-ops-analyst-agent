"""Unit tests for similarity engine core module."""

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.similarity_engine_core import (
    SimilarityMatch,
    SimilarityResult,
    _extract_counter_evidence,
    evaluate_similarity,
    freshness_weight,
)


def test_freshness_weight_recent():
    ts = datetime.now(UTC) - timedelta(minutes=30)
    weight = freshness_weight(ts)
    assert weight == 1.0


def test_freshness_weight_1h():
    ts = datetime.now(UTC) - timedelta(hours=2)
    weight = freshness_weight(ts)
    assert weight == 0.9


def test_freshness_weight_6h():
    ts = datetime.now(UTC) - timedelta(hours=12)
    weight = freshness_weight(ts)
    assert weight == 0.7


def test_freshness_weight_24h():
    ts = datetime.now(UTC) - timedelta(days=2)
    weight = freshness_weight(ts)
    assert weight == 0.5


def test_freshness_weight_old():
    ts = datetime.now(UTC) - timedelta(days=10)
    weight = freshness_weight(ts)
    assert weight == 0.3


def test_freshness_weight_none():
    weight = freshness_weight(None)
    assert weight == 0.5


def test_evaluate_similarity_empty():
    transaction = {"transaction_id": "tx-1", "amount": 100.0}
    result = evaluate_similarity(transaction, [])
    assert result.overall_score == 0.0
    assert len(result.matches) == 0


def test_evaluate_similarity_with_matches():
    transaction = {
        "transaction_id": "tx-1",
        "amount": 100.0,
        "merchant_id": "m1",
        "card_id": "c1",
        "transaction_timestamp": datetime.now(UTC),
    }
    similar = [
        {"transaction_id": "tx-2", "amount": 95.0, "merchant_id": "m1", "card_id": "c1"},
        {"transaction_id": "tx-3", "amount": 50.0, "merchant_id": "m2", "card_id": "c1"},
    ]
    result = evaluate_similarity(transaction, similar)
    assert len(result.matches) > 0
    assert result.overall_score >= 0.0


def test_evaluate_similarity_overall_averages_returned_matches():
    transaction = {
        "transaction_id": "tx-1",
        "amount": 100.0,
        "merchant_id": "m1",
        "card_id": "c1",
        "transaction_timestamp": datetime.now(UTC),
    }
    similar = [
        {"transaction_id": "tx-2", "similarity_score": 0.8},
        {"transaction_id": "tx-3", "similarity_score": 0.6},
    ]
    result = evaluate_similarity(transaction, similar)
    assert result.overall_score == pytest.approx(0.7)


def test_evaluate_similarity_reduces_approved_matches_with_counter_evidence():
    transaction = {
        "transaction_id": "tx-1",
        "amount": 100.0,
        "merchant_id": "m1",
        "card_id": "c1",
        "transaction_timestamp": datetime.now(UTC),
    }
    similar = [
        {
            "transaction_id": "tx-approved",
            "similarity_score": 0.9,
            "decision": "APPROVE",
            "three_ds_authenticated": True,
            "is_trusted_device": True,
            "avs_match": True,
        },
        {
            "transaction_id": "tx-decline",
            "similarity_score": 0.9,
            "decision": "DECLINE",
        },
    ]

    result = evaluate_similarity(transaction, similar)
    assert len(result.matches) == 2
    by_id = {match.match_id: match for match in result.matches}
    assert by_id["tx-approved"].similarity_score < by_id["tx-decline"].similarity_score
    assert by_id["tx-approved"].similarity_score < 0.5
    assert by_id["tx-approved"].details["risk_multiplier"] < 1.0


def test_similarity_match_immutable():
    match = SimilarityMatch("id", "type", 0.5, {})
    with pytest.raises(AttributeError):
        match.score = 0.9


def test_similarity_result_immutable():
    result = SimilarityResult([], 0.5)
    with pytest.raises(AttributeError):
        result.overall_score = 0.9


def test_extract_counter_evidence_3ds_and_trusted_device():
    """Test existing 3DS and trusted device counter-evidence."""
    sim_tx = {
        "three_ds_authenticated": True,
        "is_trusted_device": True,
    }
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    types = [e["type"] for e in evidence]
    assert "3ds_success" in types
    assert "trusted_device" in types


def test_extract_counter_evidence_avs_match():
    """Test AVS match counter-evidence."""
    sim_tx = {"avs_match": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "avs_match"
    assert evidence[0]["strength"] == 0.6


def test_extract_counter_evidence_cvv_match():
    """Test CVV match counter-evidence."""
    sim_tx = {"cvv_match": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "cvv_match"


def test_extract_counter_evidence_avs_response():
    """Test AVS response code 'Y' counter-evidence."""
    sim_tx = {"avs_response": "Y"}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "avs_match"


def test_extract_counter_evidence_tokenized():
    """Test tokenized payment counter-evidence."""
    sim_tx = {"is_tokenized": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "tokenized_payment"


def test_extract_counter_evidence_recurring_customer():
    """Test recurring customer counter-evidence."""
    sim_tx = {"is_recurring_customer": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "recurring_customer"


def test_extract_counter_evidence_cardholder_present():
    """Test cardholder present counter-evidence."""
    sim_tx = {"cardholder_present": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "cardholder_present"


def test_extract_counter_evidence_known_merchant():
    """Test known merchant counter-evidence."""
    sim_tx = {"is_known_merchant": True}
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 1
    assert evidence[0]["type"] == "known_merchant"


def test_extract_counter_evidence_multiple():
    """Test multiple counter-evidence types combined."""
    sim_tx = {
        "three_ds_authenticated": True,
        "is_trusted_device": True,
        "avs_match": True,
        "cvv_match": True,
        "is_tokenized": True,
    }
    result = _extract_counter_evidence(sim_tx)
    assert result is not None
    evidence = result["counter_evidence"]
    assert len(evidence) == 5
    types = [e["type"] for e in evidence]
    assert "3ds_success" in types
    assert "trusted_device" in types
    assert "avs_match" in types
    assert "cvv_match" in types
    assert "tokenized_payment" in types


def test_extract_counter_evidence_none():
    """Test no counter-evidence returns None."""
    sim_tx = {"amount": 100.0}
    result = _extract_counter_evidence(sim_tx)
    assert result is None
