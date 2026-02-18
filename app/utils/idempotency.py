"""Idempotency key computation using SHA-256."""

import hashlib


def compute_insight_key(
    transaction_id: str,
    evaluation_type: str,
    transaction_timestamp: str,
    insight_type: str,
    model_mode: str,
) -> str:
    """Compute idempotency key for insight generation."""
    components = [
        str(transaction_id),
        str(evaluation_type),
        str(transaction_timestamp),
        str(insight_type),
        str(model_mode),
    ]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_recommendation_key(
    insight_id: str,
    recommendation_type: str,
    recommendation_signature_hash: str,
) -> str:
    """Compute idempotency key for recommendations."""
    components = [str(insight_id), str(recommendation_type), str(recommendation_signature_hash)]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()


def compute_rule_draft_key(
    recommendation_id: str,
    draft_package_version: str,
) -> str:
    """Compute idempotency key for rule drafts."""
    components = [str(recommendation_id), str(draft_package_version)]
    raw = "|".join(components)
    return hashlib.sha256(raw.encode()).hexdigest()
