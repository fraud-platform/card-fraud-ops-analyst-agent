"""Unit tests for reasoning payload assembly and strict parsing."""

import pytest

from app.tools._core.reasoning_logic import assemble_prompt_payload, parse_llm_response


def test_parse_llm_response_handles_markdown_fenced_json() -> None:
    raw = """```json
{
  "narrative": "Suspicious velocity pattern observed.",
  "risk_level": "HIGH",
  "key_findings": ["burst_1h high", "decline ratio elevated"],
  "hypotheses": ["card testing"],
  "confidence": 0.82
}
```"""
    parsed = parse_llm_response(raw)

    assert parsed["risk_level"] == "HIGH"
    assert parsed["confidence"] == 0.82
    assert parsed["key_findings"][:1] == ["burst_1h high"]


def test_parse_llm_response_rejects_partial_json() -> None:
    raw = (
        "```json\n"
        '{"narrative":"Likely legitimate repeat customer activity.",'
        '"risk_level":"LOW","confidence":0.64'
    )
    with pytest.raises(ValueError, match="Unable to parse"):
        parse_llm_response(raw)


def test_parse_llm_response_accepts_single_quotes_and_trailing_commas() -> None:
    raw = """{
      'narrative': 'Suspicious merchant spread observed',
      'risk_level': 'HIGH',
      'key_findings': ['cross merchant spread'],
      'hypotheses': ['coordinated probing'],
      'confidence': 0.81,
    }"""
    parsed = parse_llm_response(raw)

    assert parsed["risk_level"] == "HIGH"
    assert parsed["confidence"] == 0.81


def test_parse_llm_response_accepts_json_wrapped_as_string() -> None:
    raw = (
        '"{\\"narrative\\":\\"Signals align\\",\\"risk_level\\":\\"MEDIUM\\",'
        '\\"key_findings\\":[\\"velocity\\"] ,\\"hypotheses\\":[],\\"confidence\\":0.66}"'
    )
    parsed = parse_llm_response(raw)

    assert parsed["risk_level"] == "MEDIUM"
    assert parsed["confidence"] == 0.66


def test_assemble_prompt_payload_uses_similarity_matches() -> None:
    context = {
        "transaction": {
            "transaction_id": "txn-123",
            "card_id": "card-123",
            "amount": 120.0,
            "currency": "USD",
            "merchant_id": "m-123",
            "decision": "APPROVE",
        }
    }
    pattern_analysis = {"patterns": []}
    similarity_analysis = {
        "matches": [
            {"transaction_id": "hist-1", "score": 0.93},
            {"match_id": "hist-2", "similarity_score": 0.81},
        ],
        "overall_score": 0.93,
    }

    payload = assemble_prompt_payload(context, pattern_analysis, similarity_analysis)

    assert "hist-1: score 0.93" in payload["similarity_analysis"]
    assert "hist-2: score 0.81" in payload["similarity_analysis"]
    assert "No similar transactions found" not in payload["similarity_analysis"]
