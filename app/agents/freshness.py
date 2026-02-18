"""Freshness weighting module - Exponential decay for evidence relevance.

This module contains ZERO database access. Pure functions for time-decay weighting.
"""

import math
from dataclasses import dataclass
from datetime import UTC, datetime

FRESHNESS_CONFIG = {
    "pattern_velocity": {
        "half_life_hours": 6.0,
        "max_weight": 1.0,
        "min_weight": 0.2,
    },
    "similarity_vector": {
        "half_life_hours": 72.0,
        "max_weight": 1.0,
        "min_weight": 0.3,
    },
    "counter_evidence_3ds": {
        "half_life_hours": 168.0,
        "max_weight": 1.0,
        "min_weight": 0.5,
    },
    "similarity_attribute": {
        "half_life_hours": 48.0,
        "max_weight": 1.0,
        "min_weight": 0.2,
    },
    "default": {
        "half_life_hours": 24.0,
        "max_weight": 1.0,
        "min_weight": 0.1,
    },
}


@dataclass(frozen=True)
class FreshnessConfig:
    half_life_hours: float
    max_weight: float
    min_weight: float


def _coerce_timestamp(transaction_timestamp: datetime | str | None) -> datetime | None:
    """Normalize timestamps from DB/API payloads into timezone-aware datetimes."""
    if transaction_timestamp is None:
        return None
    if isinstance(transaction_timestamp, datetime):
        return (
            transaction_timestamp
            if transaction_timestamp.tzinfo is not None
            else transaction_timestamp.replace(tzinfo=UTC)
        )
    if isinstance(transaction_timestamp, str):
        normalized = transaction_timestamp.strip()
        if normalized.endswith("Z"):
            normalized = normalized[:-1] + "+00:00"
        parsed = datetime.fromisoformat(normalized)
        return parsed if parsed.tzinfo is not None else parsed.replace(tzinfo=UTC)
    return None


def exponential_decay_weight(
    transaction_timestamp: datetime | str | None,
    half_life_hours: float = 24.0,
    max_weight: float = 1.0,
    min_weight: float = 0.1,
) -> float:
    """Compute exponential decay weight.

    Args:
        transaction_timestamp: When the transaction occurred
        half_life_hours: Time for weight to halve (default 24h)
        max_weight: Maximum weight (for very recent transactions)
        min_weight: Minimum weight (floor for old transactions)

    Returns:
        Weight between min_weight and max_weight
    """
    normalized_timestamp = _coerce_timestamp(transaction_timestamp)
    if normalized_timestamp is None:
        return 0.5

    now = datetime.now(UTC)
    age_hours = (now - normalized_timestamp).total_seconds() / 3600.0

    if age_hours < 0:
        return max_weight

    decay_constant = math.log(2.0) / half_life_hours
    weight = max_weight * math.exp(-decay_constant * age_hours)

    return max(weight, min_weight)


def get_freshness_config(evidence_type: str) -> FreshnessConfig:
    config = FRESHNESS_CONFIG.get(evidence_type, FRESHNESS_CONFIG["default"])
    return FreshnessConfig(**config)


def compute_freshness_weight(
    evidence_type: str,
    transaction_timestamp: datetime | str | None,
) -> float:
    """Compute freshness weight for evidence type.

    Args:
        evidence_type: Type of evidence (pattern_velocity, similarity_vector, etc.)
        transaction_timestamp: When the transaction occurred

    Returns:
        Freshness weight between min and max for the evidence type
    """
    config = get_freshness_config(evidence_type)

    return exponential_decay_weight(
        transaction_timestamp=transaction_timestamp,
        half_life_hours=config.half_life_hours,
        max_weight=config.max_weight,
        min_weight=config.min_weight,
    )


def apply_freshness_to_matches(
    matches: list[dict],
    evidence_type: str = "similarity_attribute",
) -> list[dict]:
    """Apply freshness weighting to a list of matches.

    Args:
        matches: List of match dicts with transaction_timestamp
        evidence_type: Type of evidence for config lookup

    Returns:
        Matches with freshness_weight added to details
    """
    config = get_freshness_config(evidence_type)
    weighted_matches = []

    for match in matches:
        timestamp = match.get("transaction_timestamp")
        if timestamp is None:
            freshness = 0.5
        else:
            freshness = exponential_decay_weight(
                transaction_timestamp=timestamp,
                half_life_hours=config.half_life_hours,
                max_weight=config.max_weight,
                min_weight=config.min_weight,
            )

        weighted_score = match.get("similarity_score", 0.0) * freshness

        updated_match = {
            **match,
            "similarity_score": weighted_score,
            "details": {
                **match.get("details", {}),
                "freshness_weight": freshness,
            },
        }
        weighted_matches.append(updated_match)

    return weighted_matches
