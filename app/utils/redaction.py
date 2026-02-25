"""PII redaction utility for LLM prompts and logging."""

from __future__ import annotations

import re
from typing import Any

# PII patterns for scrubbing before LLM / log output
_CARD_NUMBER_RE = re.compile(r"\b\d{13,19}\b")
_EMAIL_RE = re.compile(r"[a-zA-Z0-9_.+-]+@[a-zA-Z0-9-]+\.[a-zA-Z0-9-.]+")
_REDACTED = "***REDACTED***"
_SENSITIVE_KEY_FRAGMENTS = frozenset(
    {
        "card",
        "customer",
        "user",
        "email",
        "phone",
        "first_name",
        "last_name",
        "full_name",
        "legal_name",
        "ip",
        "address",
        "token",
        "secret",
        "auth",
        "session",
        "device",
        "note",
        "account",
        "merchant",
        "pan",
    }
)
_SENSITIVE_NAME_PARENT_FRAGMENTS = frozenset(
    {
        "customer",
        "user",
        "cardholder",
        "holder",
        "person",
        "identity",
        "profile",
        "account",
    }
)


def redact_card_id(card_id: str) -> str:
    """Redact card ID for LLM/logging: tok_abc123 -> tok_***c123"""
    if not card_id:
        return ""
    if len(card_id) > 8:
        return card_id[:4] + "***" + card_id[-4:]
    return "***REDACTED***"


def redact_pii(text: str) -> str:
    """Scrub card numbers and email addresses from free text."""
    text = _CARD_NUMBER_RE.sub("***CARD***", text)
    text = _EMAIL_RE.sub("***EMAIL***", text)
    return text


def _is_sensitive_key(key: str) -> bool:
    normalized = key.strip().lower()
    if not normalized:
        return False
    return any(fragment in normalized for fragment in _SENSITIVE_KEY_FRAGMENTS)


def _is_name_in_sensitive_context(parent_key: str) -> bool:
    normalized = parent_key.strip().lower()
    if not normalized:
        return False
    return any(fragment in normalized for fragment in _SENSITIVE_NAME_PARENT_FRAGMENTS)


def _sanitize_value(value: Any, *, parent_key: str = "") -> Any:
    if isinstance(value, dict):
        sanitized: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            key = str(raw_key)
            key_lower = key.lower()

            if key_lower == "card_id" and isinstance(raw_value, str):
                sanitized[key] = redact_card_id(raw_value)
                continue

            if key_lower == "name" and _is_name_in_sensitive_context(parent_key):
                sanitized[key] = _REDACTED
                continue

            # Free-form note payloads are frequently high risk for PII leakage.
            if key_lower in {"notes", "analyst_notes"}:
                count = len(raw_value) if isinstance(raw_value, list) else int(bool(raw_value))
                sanitized[f"{key}_count"] = count
                continue

            if _is_sensitive_key(key):
                if isinstance(raw_value, list):
                    sanitized[f"{key}_count"] = len(raw_value)
                else:
                    sanitized[key] = _REDACTED
                continue

            sanitized[key] = _sanitize_value(raw_value, parent_key=key)
        return sanitized

    if isinstance(value, list):
        if _is_sensitive_key(parent_key):
            return _REDACTED
        return [_sanitize_value(item, parent_key=parent_key) for item in value[:20]]

    if isinstance(value, str):
        if _is_sensitive_key(parent_key):
            return _REDACTED
        return redact_pii(value)

    return value


def redact_state_for_llm(state: dict[str, Any]) -> dict[str, Any]:
    """Create a redacted copy of state/context for LLM consumption."""
    if not isinstance(state, dict):
        return {}
    return _sanitize_value(state, parent_key="")
