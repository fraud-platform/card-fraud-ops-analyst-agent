"""Unit tests for reasoning core pure functions."""

import dataclasses

from app.agents.reasoning_core import (
    assemble_prompt_payload,
    merge_reasoning_with_evidence,
    parse_llm_response,
)


@dataclasses.dataclass
class _FakeTxn:
    transaction_id: str = "txn-dc"
    card_id: str = "card-dc"
    amount: float = 50.0
    currency: str = "GBP"


@dataclasses.dataclass
class _FakeVelocity:
    transaction_count_90d: int = 12
    approval_rate_90d: float = 0.85
    velocity_24h: int = 3


def test_assemble_prompt_payload_contains_expected_fields():
    payload = assemble_prompt_payload(
        context={"transaction": {"transaction_id": "txn-1", "card_id": "card-1", "amount": 10}},
        pattern_analysis={"patterns": [{"pattern_name": "velocity", "score": 0.9}]},
        similarity_analysis={"similar_transactions": [{"transaction_id": "txn-2", "score": 0.8}]},
    )

    assert payload["transaction_id"] == "txn-1"
    assert "velocity" in payload["pattern_analysis"]
    assert "txn-2" in payload["similarity_analysis"]


def test_parse_llm_response_json_codeblock():
    raw = '```json\n{"narrative":"ok","confidence":0.8}\n```'
    parsed = parse_llm_response(raw)
    assert parsed["narrative"] == "ok"
    assert parsed["confidence"] == 0.8


def test_parse_llm_response_invalid_json_fallback():
    parsed = parse_llm_response("not-json")
    assert parsed["parse_error"] is True
    assert parsed["confidence"] == 0.0


def test_merge_reasoning_with_evidence_sets_hybrid_mode():
    merged = merge_reasoning_with_evidence(
        reasoning={"narrative": "text", "risk_assessment": "HIGH", "confidence": 0.9},
        deterministic={"severity": "HIGH", "pattern_scores": [{"score": 0.9}]},
    )
    assert merged["model_mode"] == "hybrid"
    assert merged["deterministic_severity"] == "HIGH"


def test_assemble_prompt_payload_with_dataclass_transaction():
    """Tests the dataclasses.asdict() branch (line 30)."""
    txn = _FakeTxn()
    payload = assemble_prompt_payload(
        context={"transaction": txn},
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert payload["transaction_id"] == "txn-dc"
    assert payload["currency"] == "GBP"


def test_assemble_prompt_payload_with_dataclass_velocity():
    """Tests the dataclasses.asdict() branch for velocity_snapshot (line 50)."""
    velocity = _FakeVelocity()
    payload = assemble_prompt_payload(
        context={"transaction": {"transaction_id": "txn-1"}, "velocity_snapshot": velocity},
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert payload["transaction_count_90d"] == 12
    assert payload["velocity_24h"] == 3


def test_assemble_prompt_payload_counter_evidence_from_sim_result():
    """Tests sim_result.counter_evidence extraction (lines 56-58)."""

    class _FakeSimilarityResult:
        counter_evidence = [{"type": "3ds_success", "strength": 0.8}]

    payload = assemble_prompt_payload(
        context={"transaction": {}},
        pattern_analysis={"patterns": []},
        similarity_analysis={"similarity_result": _FakeSimilarityResult()},
    )
    assert "3ds_success" in payload["counter_evidence"]


def test_assemble_prompt_payload_counter_evidence_from_direct_key():
    """Tests fallback counter_evidence from similarity_analysis dict (line 60)."""
    payload = assemble_prompt_payload(
        context={"transaction": {}},
        pattern_analysis={"patterns": []},
        similarity_analysis={"counter_evidence": [{"type": "trusted_device"}]},
    )
    assert "trusted_device" in payload["counter_evidence"]


def test_assemble_prompt_payload_with_conflict_matrix():
    """Tests conflict_matrix serialization."""
    conflict_matrix = {"overall_conflict_score": 0.3, "resolution_strategy": "weighted_average"}
    payload = assemble_prompt_payload(
        context={"transaction": {}},
        pattern_analysis={"patterns": []},
        similarity_analysis={},
        conflict_matrix=conflict_matrix,
    )
    assert "weighted_average" in payload["conflict_matrix"]


def test_assemble_prompt_payload_reads_transaction_context_flags():
    """3DS and trusted-device flags should come from transaction_context when absent on transaction."""
    payload = assemble_prompt_payload(
        context={
            "transaction": {},
            "transaction_context": {"3ds_verified": True, "device_trusted": False},
        },
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert payload["three_ds_authenticated"] is True
    assert payload["device_trusted"] is False


def test_assemble_prompt_payload_expanded_counter_evidence():
    """Extended counter-evidence fields (AVS, CVV, tokenized) should come from transaction_context."""
    payload = assemble_prompt_payload(
        context={
            "transaction": {},
            "transaction_context": {
                "avs_match": True,
                "cvv_match": True,
                "is_tokenized": True,
                "is_known_merchant": True,
            },
        },
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert payload["avs_match"] is True
    assert payload["cvv_match"] is True
    assert payload["is_tokenized"] is True
    assert payload["is_known_merchant"] is True


def test_assemble_prompt_payload_counter_evidence_avs_cvv_response():
    """AVS and CVV response codes should also be accepted."""
    payload = assemble_prompt_payload(
        context={
            "transaction": {},
            "transaction_context": {
                "avs_response": "Y",
                "cvv_response": "Y",
            },
        },
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert payload["avs_match"] == "Y"
    assert payload["cvv_match"] == "Y"


def test_assemble_prompt_payload_expanded_counter_evidence_labels():
    """Expanded counter-evidence labels should appear in counter_evidence text."""
    payload = assemble_prompt_payload(
        context={
            "transaction": {},
            "transaction_context": {
                "3ds_verified": True,
                "device_trusted": True,
                "avs_match": True,
                "cvv_match": True,
                "is_tokenized": True,
                "is_known_merchant": True,
            },
        },
        pattern_analysis={"patterns": []},
        similarity_analysis={},
    )
    assert "3DS verified" in payload["counter_evidence"]
    assert "trusted device" in payload["counter_evidence"]
    assert "AVS matched" in payload["counter_evidence"]
    assert "CVV verified" in payload["counter_evidence"]
    assert "tokenized payment" in payload["counter_evidence"]
    assert "known merchant" in payload["counter_evidence"]


def test_merge_reasoning_with_evidence_parse_error_sets_deterministic():
    """Tests the parse_error → deterministic branch (line 169)."""
    merged = merge_reasoning_with_evidence(
        reasoning={"parse_error": True, "confidence": 0.0},
        deterministic={"severity": "MEDIUM"},
    )
    assert merged["model_mode"] == "deterministic"


def test_parse_llm_response_brace_extraction():
    """Tests brace-matching extraction (lines 122-132)."""
    raw = 'Some preamble {"narrative": "test", "confidence": 0.5} trailing text'
    parsed = parse_llm_response(raw)
    assert parsed["narrative"] == "test"
    assert parsed["confidence"] == 0.5
