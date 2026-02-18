"""Redaction and allowlist for LLM context."""

import re
from dataclasses import dataclass
from typing import Any

ALLOWED_FIELDS = {
    # Canonical transaction identifiers
    "transaction_id",
    "card_id",
    "card_last4",
    "amount",
    "currency",
    "timestamp",
    "decision",
    # Merchant/device context
    "merchant_id",
    "merchant_category",
    "three_ds_authenticated",
    "device_fingerprint",
    "card_age_days",
    # Velocity/aggregate context
    "transaction_count_90d",
    "approval_rate_90d",
    "velocity_24h",
    # Analysis outputs
    "pattern_analysis",
    "similarity_analysis",
    "similarity_score",
    "counter_evidence",
    "conflict_matrix",
    "insight_summary",
    "observations",
    # Legacy compatibility keys
    "card_id_hash",
    "merchant_id_hash",
    "device_id_hash",
    "severity",
    "pattern_name",
    "pattern_score",
    "score",
    "overall_score",
    "risk_score",
}

BLOCKED_FIELDS = {
    "pan",
    "card_number",
    "cardholder_name",
    "cardholder_first_name",
    "cardholder_last_name",
    "address",
    "street_address",
    "city",
    "state",
    "zip_code",
    "postal_code",
    "phone",
    "phone_number",
    "email",
    "email_address",
    "ip_address",
    "ipv4_address",
    "ipv6_address",
}


@dataclass(frozen=True)
class RedactionPolicy:
    """Defines allowed fields for LLM context."""

    allowed_fields: frozenset[str] = frozenset(ALLOWED_FIELDS)
    blocked_fields: frozenset[str] = frozenset(BLOCKED_FIELDS)

    def is_allowed(self, field: str) -> bool:
        """Check if a field is allowed."""
        return field.lower() in self.allowed_fields

    def is_blocked(self, field: str) -> bool:
        """Check if a field is explicitly blocked."""
        return field.lower() in self.blocked_fields


def redact_context(
    context: dict[str, Any],
    policy: RedactionPolicy | None = None,
) -> dict[str, Any]:
    """Strip disallowed fields from context.

    Args:
        context: Input context dict
        policy: Redaction policy (uses default if None)

    Returns:
        Context with only allowed fields
    """
    if policy is None:
        policy = RedactionPolicy()

    if not isinstance(context, dict):
        return context

    result: dict[str, Any] = {}

    for key, value in context.items():
        if policy.is_blocked(key):
            continue

        if policy.is_allowed(key):
            if isinstance(value, dict):
                redacted = redact_context(value, policy)
                result[key] = redacted
            elif isinstance(value, list):
                result[key] = [
                    redact_context(item, policy) if isinstance(item, dict) else item
                    for item in value
                ]
            else:
                result[key] = value
            continue

        # Strict allowlist mode: unknown keys are dropped.
        continue

    return result


def validate_prompt_payload(
    payload: dict[str, Any],
    policy: RedactionPolicy | None = None,
) -> list[str]:
    """Validate prompt payload for policy violations.

    Args:
        payload: Input payload to validate
        policy: Redaction policy (uses default if None)

    Returns:
        List of violation messages (empty = valid)
    """
    if policy is None:
        policy = RedactionPolicy()

    violations: list[str] = []

    def check_dict(d: dict[str, Any], path: str = "") -> None:
        for key, value in d.items():
            current_path = f"{path}.{key}" if path else key

            if policy.is_blocked(key):
                violations.append(f"Blocked field found: {current_path}")

            if isinstance(value, dict):
                check_dict(value, current_path)
            elif isinstance(value, list):
                for i, item in enumerate(value):
                    if isinstance(item, dict):
                        check_dict(item, f"{current_path}[{i}]")

    if isinstance(payload, dict):
        check_dict(payload)

    return violations


# SECURITY: Pattern-based PII detection for values that may contain PII
# These patterns catch common PII formats even in non-obvious fields

# Email: standard format
_PII_EMAIL = re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b")

# Phone: US format with optional separators
_PII_PHONE = re.compile(r"\b(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}\b")

# Credit card: 13-19 digits, spaces/dashes allowed
_PII_CREDIT_CARD = re.compile(r"\b(?:\d[ -]*?){13,19}\b")

# SSN: 123-45-6789 or 123 45 6789
_PII_SSN = re.compile(r"\b\d{3}[-\s]\d{2}[-\s]\d{4}\b")

# IP addresses (both IPv4 and IPv6)
_PII_IPV4 = re.compile(
    r"\b(?:(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(?:25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\b"
)
_PII_IPV6 = re.compile(r"\b(?:[0-9a-fA-F]{1,4}:){7}[0-9a-fA-F]{1,4}\b")

# All PII patterns combined
_PII_PATTERNS = [
    ("email", _PII_EMAIL),
    ("phone", _PII_PHONE),
    ("credit_card", _PII_CREDIT_CARD),
    ("ssn", _PII_SSN),
    ("ipv4", _PII_IPV4),
    ("ipv6", _PII_IPV6),
]


def detect_pii_in_values(payload: dict[str, Any]) -> list[str]:
    """Detect PII patterns in string values across the payload.

    SECURITY: This is a defense-in-depth check to catch PII that may appear
    in unexpected fields (e.g., a phone number in a "notes" field). Does not
    replace field-based redaction but adds an extra layer of protection.

    Args:
        payload: Input payload to scan

    Returns:
        List of PII detection messages (empty = no PII detected)
    """
    violations: list[str] = []

    def check_value(value: Any, path: str) -> None:
        if isinstance(value, str):
            for pattern_name, pattern in _PII_PATTERNS:
                matches = pattern.findall(value)
                if matches:
                    violations.append(
                        f"Potential {pattern_name} detected at {path}: {len(matches)} occurrence(s)"
                    )
        elif isinstance(value, dict):
            for k, v in value.items():
                check_value(v, f"{path}.{k}" if path else k)
        elif isinstance(value, list):
            for i, item in enumerate(value):
                check_value(item, f"{path}[{i}]" if path else f"[{i}]")

    if isinstance(payload, dict):
        check_value(payload, "")

    return violations
