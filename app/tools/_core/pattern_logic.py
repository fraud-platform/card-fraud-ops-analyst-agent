"""Pattern engine core - PURE functions for anomaly scoring and severity classification.

This module contains ZERO database access. Pure functions operating on in-memory data structures.
"""

import math
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from app.utils.constants import RISK_MERCHANT_CATEGORIES


@dataclass(frozen=True)
class PatternScore:
    """Immutable pattern score."""

    pattern_name: str
    score: float
    weight: float
    details: dict[str, Any]


ROUND_NUMBER_THRESHOLDS: list[int] = [100, 200, 300, 400, 500, 750, 1000, 1500, 2000, 5000, 10000]


def _is_round_number(amount: float, thresholds: list[int] | None = None) -> bool:
    """Check if amount is a round number that may indicate fraud."""
    if thresholds is None:
        thresholds = ROUND_NUMBER_THRESHOLDS

    if amount <= 0:
        return False

    integer_part = int(amount)
    decimal_part = amount - integer_part

    if decimal_part == 0:
        return integer_part in thresholds

    if decimal_part == 0.99:
        adjusted = integer_part + 1
        return adjusted in thresholds

    return False


def _calculate_mean(values: list[float]) -> float:
    """Calculate mean of a list of values."""
    if not values:
        return 0.0
    return sum(values) / len(values)


def _calculate_std_dev(values: list[float], mean: float) -> float:
    """Calculate standard deviation."""
    if len(values) < 2:
        return 0.0
    variance = sum((x - mean) ** 2 for x in values) / len(values)
    return math.sqrt(variance)


def score_amount_anomalies(
    transaction: Any,
    card_history: list[dict[str, Any]],
    window_stats: dict[int, Any],
    round_thresholds: list[int] | None = None,
    high_threshold: float = 1000.0,
    elevated_threshold: float = 500.0,
    zscore_outlier: float = 3.0,
    zscore_warning: float = 2.0,
) -> PatternScore:
    """Score amount-based anomalies.

    Detects:
    - Round numbers (e.g., $500, $1000) - common in fraud
    - Statistical outliers compared to card history
    - High absolute amounts
    """
    score = 0.0
    weight = 0.35
    details: dict[str, Any] = {}

    if transaction is None:
        return PatternScore(
            pattern_name="amount_anomaly",
            score=0.0,
            weight=weight,
            details={},
        )

    if hasattr(transaction, "amount"):
        amount = float(transaction.amount)
    elif isinstance(transaction, dict):
        amount = float(transaction.get("amount", 0))
    else:
        amount = 0.0

    if amount > 0:
        if _is_round_number(amount, round_thresholds):
            score = 0.7
            details["round_number"] = True
            details["amount"] = amount

        if amount > high_threshold:
            score = max(score, 0.8)
            details["high_amount"] = amount
        elif amount > elevated_threshold:
            score = max(score, 0.5)
            details["elevated_amount"] = amount

    historical_amounts = []
    for txn in card_history:
        txn_amount = txn.get("amount")
        if txn_amount is not None:
            try:
                historical_amounts.append(float(txn_amount))
            except TypeError, ValueError:
                pass

    if historical_amounts:
        mean = _calculate_mean(historical_amounts)
        std_dev = _calculate_std_dev(historical_amounts, mean)

        if mean > 0 and std_dev > 0 and amount > 0:
            z_score = (amount - mean) / std_dev
            if z_score > zscore_outlier:
                score = max(score, 0.9)
                details["z_score"] = round(z_score, 2)
                details["mean"] = round(mean, 2)
                details["std_dev"] = round(std_dev, 2)
                details["outlier"] = True
            elif z_score > zscore_warning:
                score = max(score, 0.7)
                details["z_score"] = round(z_score, 2)
                details["outlier"] = True

    if window_stats.get(24):
        stats = window_stats[24]
        if stats.transaction_count > 0:
            try:
                total_amount = float(stats.total_amount)
            except TypeError, ValueError:
                total_amount = 0.0
            avg_amount = total_amount / float(stats.transaction_count)
            if amount > avg_amount * 3 and avg_amount > 0:
                score = max(score, 0.6)
                details["spike_vs_avg"] = round(amount / avg_amount, 2)

    return PatternScore(
        pattern_name="amount_anomaly",
        score=score,
        weight=weight,
        details=details,
    )


HIGH_RISK_HOURS = (0, 1, 2, 3, 4, 5)


def _get_hour_from_timestamp(ts: Any) -> int | None:
    """Extract hour from various timestamp formats."""
    if ts is None:
        return None

    if isinstance(ts, datetime):
        return ts.hour

    if isinstance(ts, str):
        try:
            dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            return dt.hour
        except ValueError, AttributeError:
            pass

    return None


def _is_unusual_hour(hour: int, unusual_hours: list[int] | None = None) -> bool:
    """Check if hour is unusual (late night/early morning)."""
    if unusual_hours is None:
        unusual_hours = [0, 1, 2, 3, 4, 5]
    return hour in unusual_hours


def _get_merchant_category_risk(mcc: str | None) -> str:
    """Get risk level for merchant category code."""
    if mcc is None:
        return "low"

    mcc_str = str(mcc).zfill(4)

    for category, mccs in RISK_MERCHANT_CATEGORIES.items():
        if mcc_str in mccs:
            return category

    return "low"


def score_card_testing(
    transaction: Any,
    card_history: list[dict[str, Any]],
) -> PatternScore:
    """Score card testing patterns.

    Detects:
    - Multiple small amounts increasing over time (card testing)
    - Same merchant or different merchants
    - Short time window (minutes apart)
    - High decline rate in sequence

    Card testing is a common fraud pattern where attackers test
    stolen card numbers with small purchases before making larger ones.
    """
    score = 0.0
    weight = 0.35
    details: dict[str, Any] = {}

    if transaction is None or not card_history:
        return PatternScore(
            pattern_name="card_testing",
            score=0.0,
            weight=weight,
            details={},
        )

    current_amount = 0.0
    if hasattr(transaction, "amount"):
        current_amount = float(getattr(transaction, "amount", 0))
    elif isinstance(transaction, dict):
        current_amount = float(transaction.get("amount", 0))

    current_timestamp = None
    if hasattr(transaction, "transaction_timestamp"):
        current_timestamp = getattr(transaction, "transaction_timestamp", None)
    elif isinstance(transaction, dict):
        ts = transaction.get("transaction_timestamp")
        if isinstance(ts, str):
            try:
                current_timestamp = datetime.fromisoformat(ts.replace("Z", "+00:00"))
            except ValueError:
                pass
        else:
            current_timestamp = ts

    sorted_history = sorted(
        card_history, key=lambda x: x.get("transaction_timestamp", ""), reverse=True
    )

    recent_txns_with_ts: list[tuple[datetime, dict[str, Any]]] = []
    for txn in sorted_history[:10]:
        txn_ts = txn.get("transaction_timestamp")
        if txn_ts:
            if isinstance(txn_ts, str):
                try:
                    txn_dt = datetime.fromisoformat(txn_ts.replace("Z", "+00:00"))
                except ValueError:
                    continue
            else:
                txn_dt = txn_ts

            if current_timestamp and txn_dt:
                time_diff = abs((current_timestamp - txn_dt).total_seconds() / 60)
                if time_diff <= 60:
                    recent_txns_with_ts.append((txn_dt, txn))

    # Analyze recent attempts in chronological order to detect true amount ladders.
    recent_txns_with_ts.sort(key=lambda item: item[0])
    recent_txns = [txn for _, txn in recent_txns_with_ts]

    if len(recent_txns) >= 3:
        amounts = [
            float(txn.get("amount", 0)) for txn in recent_txns if txn.get("amount") is not None
        ]
        amounts.append(current_amount)

        if len(amounts) >= 3:
            increasing = all(amounts[i] < amounts[i + 1] for i in range(len(amounts) - 1))

            if increasing and amounts[-1] > amounts[0] * 2:
                score = 0.8
                details["increasing_sequence"] = True
                details["sequence_length"] = len(amounts)
                details["amount_range"] = f"{amounts[0]:.2f} - {amounts[-1]:.2f}"

    decline_count = 0
    for txn in recent_txns:
        status = txn.get("status") or txn.get("decision")
        if status and str(status).upper() == "DECLINE":
            decline_count += 1

    if len(recent_txns) >= 2:
        decline_rate = decline_count / len(recent_txns)
        if decline_rate >= 0.5:
            score = max(score, 0.7)
            details["high_decline_rate"] = True
            details["decline_rate"] = round(decline_rate, 2)
            details["recent_decline_count"] = decline_count

    merchant_ids = set()
    for txn in recent_txns:
        m_id = txn.get("merchant_id")
        if m_id:
            merchant_ids.add(m_id)

    if hasattr(transaction, "merchant_id"):
        m_id = getattr(transaction, "merchant_id", None)
        if m_id:
            merchant_ids.add(m_id)
    elif isinstance(transaction, dict):
        m_id = transaction.get("merchant_id")
        if m_id:
            merchant_ids.add(m_id)

    if len(merchant_ids) >= 3:
        score = max(score, 0.6)
        details["multiple_merchants"] = True
        details["unique_merchants"] = len(merchant_ids)

    if current_amount > 0 and current_amount < 10:
        small_count = sum(1 for txn in recent_txns if float(txn.get("amount", 0)) < 10)
        if small_count >= 2:
            score = max(score, 0.7)
            details["small_amount_sequence"] = True
            details["small_txn_count"] = small_count + 1

    return PatternScore(
        pattern_name="card_testing",
        score=score,
        weight=weight,
        details=details,
    )


def score_time_anomalies(
    transaction: Any,
    card_history: list[dict[str, Any]],
    transaction_context: dict[str, Any] | None = None,
    unusual_hours: list[int] | None = None,
) -> PatternScore:
    """Score time-based anomalies.

    Detects:
    - Unusual hours (late night/early morning)
    - Timezone mismatch (IP country vs expected)
    - First transaction at unusual hour for cardholder
    """
    if unusual_hours is None:
        unusual_hours = [0, 1, 2, 3, 4, 5]

    score = 0.0
    weight = 0.25
    details: dict[str, Any] = {}

    if transaction is None:
        return PatternScore(
            pattern_name="time_anomaly",
            score=0.0,
            weight=weight,
            details={},
        )

    if hasattr(transaction, "transaction_timestamp"):
        tx_timestamp = transaction.transaction_timestamp
    elif isinstance(transaction, dict):
        tx_timestamp = transaction.get("transaction_timestamp")
    else:
        tx_timestamp = None

    hour = _get_hour_from_timestamp(tx_timestamp)

    if hour is not None:
        if _is_unusual_hour(hour, unusual_hours):
            score = 0.4
            details["unusual_hour"] = hour
            details["hour_category"] = "late_night"

        mcc = None
        if hasattr(transaction, "merchant_category"):
            mcc = getattr(transaction, "merchant_category", None)
        elif isinstance(transaction, dict):
            mcc = transaction.get("merchant_category") or transaction.get("merchant_category_code")

        merchant_risk = _get_merchant_category_risk(mcc)
        details["merchant_category"] = str(mcc) if mcc else "unknown"
        details["merchant_risk"] = merchant_risk

        if merchant_risk == "high" and hour in HIGH_RISK_HOURS:
            score = max(score, 0.8)
            details["high_risk_combo"] = True

    ip_country = None
    card_country = None
    if transaction_context:
        ip_country = transaction_context.get("ip_country")
        card_country = transaction_context.get("card_country")

    if ip_country and card_country and ip_country != card_country:
        score = max(score, 0.9)
        details["timezone_mismatch"] = True
        details["ip_country"] = ip_country
        details["card_country"] = card_country

    historical_hours = []
    for txn in card_history:
        txn_ts = txn.get("transaction_timestamp") if isinstance(txn, dict) else None
        if txn_ts:
            h = _get_hour_from_timestamp(txn_ts)
            if h is not None:
                historical_hours.append(h)

    if historical_hours and hour is not None:
        usual_hours = set(historical_hours)
        if hour not in usual_hours:
            if len(historical_hours) >= 5:
                score = max(score, 0.6)
                details["unusual_hour_for_cardholder"] = True
                details["usual_hours"] = sorted(list(usual_hours))

    return PatternScore(
        pattern_name="time_anomaly",
        score=score,
        weight=weight,
        details=details,
    )


def score_velocity_patterns(
    window_stats: dict[int, Any],
    signals: list[Any],
    burst_1h_threshold: int = 10,
    burst_6h_threshold: int = 20,
) -> PatternScore:
    """Score velocity-based patterns."""
    score = 0.0
    weight = 0.4
    details = {}

    if window_stats.get(1):
        stats = window_stats[1]
        if stats.transaction_count > burst_1h_threshold:
            score = 0.9
            details["burst_1h"] = stats.transaction_count
        elif stats.transaction_count > burst_1h_threshold // 2:
            score = 0.6
            details["burst_1h"] = stats.transaction_count

    if window_stats.get(6):
        stats = window_stats[6]
        if stats.transaction_count > burst_6h_threshold:
            score = max(score, 0.8)
            details["burst_6h"] = stats.transaction_count

    for signal in signals:
        if signal.name == "burst_1h":
            score = max(score, 0.7)
            break

    return PatternScore(
        pattern_name="velocity",
        score=score,
        weight=weight,
        details=details,
    )


def score_decline_anomalies(
    window_stats: dict[int, Any],
    signals: list[Any],
    high_threshold: float = 0.5,
    medium_threshold: float = 0.3,
) -> PatternScore:
    """Score decline rate anomalies."""
    score = 0.0
    weight = 0.3
    details = {}

    if window_stats.get(24):
        stats = window_stats[24]
        if stats.transaction_count > 0:
            decline_ratio = stats.decline_count / stats.transaction_count
            if decline_ratio > high_threshold:
                score = 0.9
                details["decline_ratio_24h"] = decline_ratio
            elif decline_ratio > medium_threshold:
                score = 0.6
                details["decline_ratio_24h"] = decline_ratio

    for signal in signals:
        if signal.name == "high_decline_rate":
            score = max(score, 0.7)
            break

    return PatternScore(
        pattern_name="decline_anomaly",
        score=score,
        weight=weight,
        details=details,
    )


def score_cross_merchant_patterns(
    window_stats: dict[int, Any],
    context: Any,
    high_threshold: int = 10,
    medium_threshold: int = 5,
) -> PatternScore:
    """Score cross-merchant patterns."""
    score = 0.0
    weight = 0.3
    details = {}

    if window_stats.get(24):
        stats = window_stats[24]
        if stats.unique_merchants > high_threshold:
            score = 0.8
            details["unique_merchants_24h"] = stats.unique_merchants
        elif stats.unique_merchants > medium_threshold:
            score = 0.5
            details["unique_merchants_24h"] = stats.unique_merchants

    return PatternScore(
        pattern_name="cross_merchant",
        score=score,
        weight=weight,
        details=details,
    )


def run_pattern_scoring(
    context: dict[str, Any],
    thresholds: dict[str, Any] | None = None,
) -> list[PatternScore]:
    """Run all pattern scoring algorithms.

    Args:
        context: Transaction context with windows, signals, transaction, card_history
        thresholds: Optional dict to override default thresholds. Keys:
            - round_number_thresholds: list[int]
            - amount_high_threshold: float
            - amount_elevated_threshold: float
            - amount_zscore_outlier_threshold: float
            - amount_zscore_warning_threshold: float
            - velocity_burst_1h_threshold: int
            - velocity_burst_6h_threshold: int
            - decline_ratio_high_threshold: float
            - decline_ratio_medium_threshold: float
            - cross_merchant_high_threshold: int
            - cross_merchant_medium_threshold: int
            - time_unusual_hours: list[int]
    """
    if thresholds is None:
        thresholds = {}

    window_stats = context.get("windows", {})
    signals = context.get("signals", [])
    transaction = context.get("transaction")
    card_history = context.get("card_history", [])
    transaction_context = context.get("transaction_context", {})

    round_thresholds = thresholds.get("round_number_thresholds", ROUND_NUMBER_THRESHOLDS)

    scores = [
        score_amount_anomalies(
            transaction,
            card_history,
            window_stats,
            round_thresholds,
            thresholds.get("amount_high_threshold", 1000),
            thresholds.get("amount_elevated_threshold", 500),
            thresholds.get("amount_zscore_outlier_threshold", 3.0),
            thresholds.get("amount_zscore_warning_threshold", 2.0),
        ),
        score_time_anomalies(
            transaction,
            card_history,
            transaction_context,
            thresholds.get("time_unusual_hours", [0, 1, 2, 3, 4, 5]),
        ),
        score_velocity_patterns(
            window_stats,
            signals,
            thresholds.get("velocity_burst_1h_threshold", 10),
            thresholds.get("velocity_burst_6h_threshold", 20),
        ),
        score_decline_anomalies(
            window_stats,
            signals,
            thresholds.get("decline_ratio_high_threshold", 0.5),
            thresholds.get("decline_ratio_medium_threshold", 0.3),
        ),
        score_cross_merchant_patterns(
            window_stats,
            transaction,
            thresholds.get("cross_merchant_high_threshold", 10),
            thresholds.get("cross_merchant_medium_threshold", 5),
        ),
        score_card_testing(transaction, card_history),
    ]

    return scores


def compute_severity(pattern_scores: list[PatternScore]) -> str:
    """Compute overall severity from pattern scores."""
    if not pattern_scores:
        return "LOW"

    score_by_name = {s.pattern_name: float(s.score) for s in pattern_scores}
    network_signal_names = ("velocity", "decline_anomaly", "cross_merchant", "card_testing")
    network_scores = [score_by_name.get(name, 0.0) for name in network_signal_names]
    network_medium_count = sum(1 for value in network_scores if value >= 0.5)
    network_strong_count = sum(1 for value in network_scores if value >= 0.7)

    weighted_sum = sum(s.score * s.weight for s in pattern_scores)
    total_weight = sum(s.weight for s in pattern_scores)
    max_score = max((s.score for s in pattern_scores), default=0.0)
    medium_signal_count = sum(1 for s in pattern_scores if s.score >= 0.5)

    if total_weight > 0:
        normalized_score = weighted_sum / total_weight
    else:
        normalized_score = 0.0

    if normalized_score >= 0.7:
        return "CRITICAL"

    # Promote concentrated core-fraud signals before weighted averages can dilute them.
    if network_strong_count >= 2:
        return "HIGH"
    if max_score >= 0.9 and network_medium_count >= 1:
        return "HIGH"

    elif normalized_score >= 0.5:
        return "HIGH"
    elif normalized_score >= 0.3:
        return "MEDIUM"

    # Keep isolated single-dimension signals (for example unusual hour only)
    # advisory; require corroboration for MEDIUM promotion.
    if medium_signal_count >= 3:
        return "MEDIUM"
    if network_medium_count >= 2:
        return "MEDIUM"
    if network_strong_count >= 1 and medium_signal_count >= 2:
        return "MEDIUM"
    return "LOW"


@dataclass(frozen=True)
class FeatureAttribution:
    """Attribution for a single feature's contribution to the risk score."""

    feature_name: str
    raw_score: float
    weight: float
    weighted_contribution: float
    contribution_percentage: float
    is_top_contributor: bool


def compute_feature_attributions(pattern_scores: list[PatternScore]) -> list[FeatureAttribution]:
    """Compute feature attributions showing each pattern's contribution to overall risk.

    This provides SHAP-like explainability by showing how each pattern contributes
    to the final risk assessment, enabling auditors and analysts to understand
    which signals drove the decision.

    Args:
        pattern_scores: List of PatternScore objects from pattern analysis

    Returns:
        List of FeatureAttribution objects sorted by contribution (descending)
    """
    if not pattern_scores:
        return []

    total_weighted = sum(s.score * s.weight for s in pattern_scores)
    total_weight = sum(s.weight for s in pattern_scores)

    if total_weighted <= 0 or total_weight <= 0:
        return [
            FeatureAttribution(
                feature_name=s.pattern_name,
                raw_score=s.score,
                weight=s.weight,
                weighted_contribution=0.0,
                contribution_percentage=0.0,
                is_top_contributor=False,
            )
            for s in pattern_scores
        ]

    weighted_contributions = [(s.score * s.weight) for s in pattern_scores]
    max_contribution = max(weighted_contributions) if weighted_contributions else 0.0

    attributions: list[FeatureAttribution] = []
    for i, s in enumerate(pattern_scores):
        contribution = weighted_contributions[i]
        percentage = (contribution / total_weighted) * 100.0 if total_weighted > 0 else 0.0
        is_top = contribution >= max_contribution and contribution > 0

        attributions.append(
            FeatureAttribution(
                feature_name=s.pattern_name,
                raw_score=round(s.score, 4),
                weight=round(s.weight, 4),
                weighted_contribution=round(contribution, 4),
                contribution_percentage=round(percentage, 2),
                is_top_contributor=is_top,
            )
        )

    attributions.sort(key=lambda a: a.weighted_contribution, reverse=True)

    if attributions:
        top_contributions = [a.weighted_contribution for a in attributions]
        max_val = max(top_contributions) if top_contributions else 0
        for attr in attributions:
            object.__setattr__(
                attr,
                "is_top_contributor",
                attr.weighted_contribution >= max_val and attr.weighted_contribution > 0,
            )

    return attributions


def format_attribution_summary(attributions: list[FeatureAttribution], max_items: int = 5) -> str:
    """Format feature attributions as a human-readable summary string.

    Args:
        attributions: List of FeatureAttribution objects
        max_items: Maximum number of items to include in summary

    Returns:
        Formatted summary string for logging/display
    """
    if not attributions:
        return "No pattern signals detected"

    top = [a for a in attributions if a.weighted_contribution > 0][:max_items]
    if not top:
        return "No significant risk patterns detected"

    lines = []
    for a in top:
        marker = " [TOP]" if a.is_top_contributor else ""
        lines.append(f"{a.feature_name}: {a.contribution_percentage:.1f}%{marker}")

    return " | ".join(lines)
