"""Recommendation engine core - PURE functions for policy rules and candidate generation.

This module contains ZERO database access. Pure functions operating on in-memory data structures.
"""

from dataclasses import dataclass
from typing import Any

from app.utils.data_access import as_dict, get_attr


@dataclass(frozen=True)
class RecommendationCandidate:
    """Immutable recommendation candidate."""

    recommendation_type: str
    priority: int
    title: str
    impact: str
    signature_hash: str


def _pattern_value(pattern: Any, name: str, default: float = 0.0) -> float:
    if get_attr(pattern, "pattern_name") != name:
        return default
    return float(get_attr(pattern, "score", default))


def _pattern_scores(pattern_scores: list[Any], name: str) -> float:
    for pattern in pattern_scores:
        score = _pattern_value(pattern, name, default=-1.0)
        if score >= 0.0:
            return score
    return 0.0


def _pattern_details(pattern_scores: list[Any], name: str) -> dict[str, Any]:
    for pattern in pattern_scores:
        if get_attr(pattern, "pattern_name") != name:
            continue
        details = get_attr(pattern, "details", {})
        return details if isinstance(details, dict) else {}
    return {}


def _similarity_overall(similarity_result: Any) -> float:
    if similarity_result is None:
        return 0.0
    return float(get_attr(similarity_result, "overall_score", 0.0))


def generate_recommendations(
    pattern_scores: list[Any],
    similarity_result: Any,
    severity: str,
    context: dict[str, Any],
) -> list[RecommendationCandidate]:
    """Generate context-aware recommendation candidates based on analysis.

    Recommendations include transaction-specific details so fraud analysts
    can make informed decisions without needing to open additional tools.
    """
    candidates = []

    # Extract transaction context for enriched recommendations
    transaction = context.get("transaction")
    velocity = context.get("velocity_snapshot") or {}

    amount = get_attr(transaction, "amount", 0) if transaction else 0
    merchant_id = get_attr(transaction, "merchant_id", "unknown") if transaction else "unknown"

    v24h = as_dict(velocity).get("velocity_24h", "unknown")
    amount_details = _pattern_details(pattern_scores, "amount_anomaly")
    time_details = _pattern_details(pattern_scores, "time_anomaly")
    cross_details = _pattern_details(pattern_scores, "cross_merchant")
    card_testing_details = _pattern_details(pattern_scores, "card_testing")

    if severity in ("CRITICAL", "HIGH"):
        candidates.append(
            RecommendationCandidate(
                recommendation_type="review_priority",
                priority=1,
                title="High-priority manual review required",
                impact=(
                    f"${float(amount):.2f} transaction at {merchant_id} "
                    f"shows {severity} fraud indicators. Immediate analyst review recommended."
                ),
                signature_hash="review_priority_1",
            )
        )

    card_testing_score = _pattern_scores(pattern_scores, "card_testing")
    if card_testing_score >= 0.6:
        sequence_length = card_testing_details.get("sequence_length", "multiple")
        amount_range = card_testing_details.get("amount_range", "small escalating amounts")
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=1,
                title="Escalate card-testing sequence investigation",
                impact=(
                    f"Card-testing score {card_testing_score:.2f} with sequence length {sequence_length} "
                    f"and range {amount_range}. Review related authorization attempts immediately."
                ),
                signature_hash="case_card_testing_1",
            )
        )

    velocity_score = _pattern_scores(pattern_scores, "velocity")
    if velocity_score >= 0.6:
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=2,
                title="Create velocity investigation case",
                impact=(
                    f"Velocity score {velocity_score:.2f} — {v24h} transactions in 24h. "
                    f"Review card activity for burst pattern at {merchant_id}."
                ),
                signature_hash="case_velocity_1",
            )
        )

    decline_score = _pattern_scores(pattern_scores, "decline_anomaly")
    if decline_score >= 0.5:
        candidates.append(
            RecommendationCandidate(
                recommendation_type="rule_candidate",
                priority=3,
                title="Refine velocity threshold for merchant cluster",
                impact=(
                    f"Decline anomaly score {decline_score:.2f} at {merchant_id}. "
                    f"Expected to reduce repeat false negatives by tightening velocity limits."
                ),
                signature_hash="rule_decline_1",
            )
        )
    if decline_score >= 0.8:
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=2,
                title="Escalate sustained decline anomaly case",
                impact=(
                    f"Decline anomaly score {decline_score:.2f} indicates persistent elevated decline "
                    f"behavior at {merchant_id}. Validate cardholder activity and recent merchant attempts."
                ),
                signature_hash="case_decline_escalation_1",
            )
        )

    cross_score = _pattern_scores(pattern_scores, "cross_merchant")
    if cross_score >= 0.5:
        merchants_24h = cross_details.get("unique_merchants_24h", "multiple")
        candidates.append(
            RecommendationCandidate(
                recommendation_type="rule_candidate",
                priority=3,
                title="Review cross-merchant spread controls",
                impact=(
                    f"Cross-merchant score {cross_score:.2f} with {merchants_24h} merchants in 24h. "
                    "Assess merchant-cluster thresholds and coordinated testing controls."
                ),
                signature_hash="rule_cross_merchant_1",
            )
        )

    amount_score = _pattern_scores(pattern_scores, "amount_anomaly")
    if amount_score >= 0.5:
        high_amount = amount_details.get("high_amount") or amount_details.get("elevated_amount")
        amount_text = (
            f"${float(high_amount):.2f}" if isinstance(high_amount, int | float) else "elevated"
        )
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=2,
                title="Validate amount anomaly against card baseline",
                impact=(
                    f"Amount anomaly score {amount_score:.2f}: transaction amount {amount_text} at "
                    f"{merchant_id}. Compare against historical spend and merchant-category behavior."
                ),
                signature_hash="case_amount_anomaly_1",
            )
        )

    time_score = _pattern_scores(pattern_scores, "time_anomaly")
    if time_score >= 0.5:
        unusual_hour = time_details.get("unusual_hour")
        timezone_mismatch = bool(time_details.get("timezone_mismatch"))
        time_signals: list[str] = []
        if unusual_hour is not None:
            time_signals.append(f"unusual hour {unusual_hour}:00")
        if timezone_mismatch:
            ip_country = time_details.get("ip_country", "?")
            card_country = time_details.get("card_country", "?")
            time_signals.append(f"timezone mismatch {ip_country}/{card_country}")
        signal_text = ", ".join(time_signals) if time_signals else "time-based anomaly"
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=3,
                title="Review temporal risk indicators",
                impact=(
                    f"Time anomaly score {time_score:.2f}: {signal_text}. Validate cardholder "
                    "availability and channel telemetry before closure."
                ),
                signature_hash="case_time_anomaly_1",
            )
        )

    if _similarity_overall(similarity_result) >= 0.5:
        sim_score = _similarity_overall(similarity_result)
        candidates.append(
            RecommendationCandidate(
                recommendation_type="rule_candidate",
                priority=4,
                title="Add cross-merchant pattern detection rule",
                impact=(
                    f"Similarity score {sim_score:.2f} — transaction pattern matches "
                    f"prior confirmed fraud. Adding a rule could improve detection of "
                    f"card testing across merchants."
                ),
                signature_hash="rule_similarity_1",
            )
        )

    if not candidates:
        candidates.append(
            RecommendationCandidate(
                recommendation_type="review_priority",
                priority=5,
                title="Standard review — no significant anomalies",
                impact=(
                    f"${float(amount):.2f} transaction at {merchant_id} shows no "
                    f"significant anomalous patterns. Routine review recommended."
                ),
                signature_hash="standard_review_1",
            )
        )

    return candidates
