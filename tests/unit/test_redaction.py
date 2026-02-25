"""Unit tests for LLM/log redaction utilities."""

from __future__ import annotations

from app.utils.redaction import redact_state_for_llm


def test_redact_state_for_llm_masks_sensitive_keys_and_notes() -> None:
    payload = {
        "transaction": {
            "transaction_id": "txn-123",
            "card_id": "tok_abcdef123456",
            "user_id": "user-123",
            "merchant_id": "merchant-456",
            "amount": 199.99,
        },
        "analyst_notes": [
            {"note": "Card 4111111111111111 and email alice@example.com"},
        ],
        "free_text": "customer email is bob@example.com",
    }

    redacted = redact_state_for_llm(payload)

    assert redacted["transaction"]["transaction_id"] == "txn-123"
    assert redacted["transaction"]["amount"] == 199.99
    assert redacted["transaction"]["card_id"] != "tok_abcdef123456"
    assert redacted["transaction"]["user_id"] == "***REDACTED***"
    assert redacted["transaction"]["merchant_id"] == "***REDACTED***"
    assert redacted["analyst_notes_count"] == 1
    assert "***EMAIL***" in redacted["free_text"]


def test_redact_state_for_llm_replaces_sensitive_nested_collections() -> None:
    payload = {
        "context": {
            "customer_history": [{"ip_address": "10.0.0.1"}, {"ip_address": "10.0.0.2"}],
            "signals": [{"name": "velocity_spike"}],
        }
    }

    redacted = redact_state_for_llm(payload)

    assert redacted["context"]["customer_history_count"] == 2
    assert redacted["context"]["signals"] == [{"name": "velocity_spike"}]


def test_redact_state_for_llm_masks_name_in_sensitive_context_only() -> None:
    payload = {
        "holder_profile": {"name": "Alice Example"},
        "signals": [{"name": "velocity_spike"}],
    }

    redacted = redact_state_for_llm(payload)

    assert redacted["holder_profile"]["name"] == "***REDACTED***"
    assert redacted["signals"] == [{"name": "velocity_spike"}]
