"""Unit tests for redaction policies."""

from app.llm.redaction import (
    RedactionPolicy,
    detect_pii_in_values,
    redact_context,
    validate_prompt_payload,
)


def test_redact_context_removes_blocked_fields():
    context = {
        "transaction_id": "txn-1",
        "pan": "4111111111111111",
        "nested": {"email": "a@b.com", "amount": 25},
    }

    redacted = redact_context(context, RedactionPolicy())

    assert "pan" not in redacted
    assert "nested" not in redacted
    assert redacted["transaction_id"] == "txn-1"


def test_validate_prompt_payload_detects_violations():
    payload = {"safe": "x", "ip_address": "1.2.3.4", "nested": {"phone": "555"}}
    violations = validate_prompt_payload(payload, RedactionPolicy())
    assert any("ip_address" in v for v in violations)
    assert any("phone" in v for v in violations)


def test_detect_pii_in_values_finds_common_patterns():
    payload = {
        "insight_summary": "contact john@example.com from 1.2.3.4",
        "observations": ["use card 4111 1111 1111 1111"],
    }
    violations = detect_pii_in_values(payload)
    assert any("email" in v for v in violations)
    assert any("ipv4" in v for v in violations)
    assert any("credit_card" in v for v in violations)
