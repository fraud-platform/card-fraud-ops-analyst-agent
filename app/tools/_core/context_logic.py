"""Context builder core - PURE functions for feature extraction and window stats.

This module contains ZERO database access. Pure functions operating on in-memory data structures.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any


@dataclass(frozen=True)
class TransactionContext:
    """Immutable transaction context."""

    transaction_id: str
    amount: float
    currency: str
    merchant_id: str
    merchant_name: str
    card_id: str
    card_last_four: str
    transaction_timestamp: datetime
    status: str
    decline_reason: str | None
    velocity_score: float | None
    fraud_score: float | None


@dataclass(frozen=True)
class WindowStats:
    """Immutable window statistics."""

    window_hours: int
    transaction_count: int
    total_amount: float
    decline_count: int
    unique_merchants: int
    unique_cards: int


@dataclass(frozen=True)
class Signal:
    """Immutable signal extracted from context."""

    name: str
    value: Any
    weight: float


def _is_decline_status(status: str | None) -> bool:
    """Normalize decline status variants used across test fixtures and TM data."""
    if status is None:
        return False
    normalized = status.strip().upper()
    return normalized in {"DECLINE", "DECLINED"}


def _coerce_datetime(value: Any) -> datetime | None:
    """Convert supported timestamp representations into UTC-aware datetimes."""
    if isinstance(value, datetime):
        if value.tzinfo is None:
            return value.replace(tzinfo=UTC)
        return value.astimezone(UTC)

    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
        if parsed.tzinfo is None:
            return parsed.replace(tzinfo=UTC)
        return parsed.astimezone(UTC)

    return None


def compute_window_stats(transactions: list[dict[str, Any]], window_hours: int) -> WindowStats:
    """Compute statistics for a time window."""
    if not transactions:
        return WindowStats(
            window_hours=window_hours,
            transaction_count=0,
            total_amount=0.0,
            decline_count=0,
            unique_merchants=0,
            unique_cards=0,
        )

    total_amount = sum(float(t.get("amount", 0) or 0) for t in transactions)
    decline_count = sum(1 for t in transactions if _is_decline_status(t.get("status")))
    unique_merchants = len(set(t.get("merchant_id") for t in transactions if t.get("merchant_id")))
    unique_cards = len(set(t.get("card_id") for t in transactions if t.get("card_id")))

    return WindowStats(
        window_hours=window_hours,
        transaction_count=len(transactions),
        total_amount=total_amount,
        decline_count=decline_count,
        unique_merchants=unique_merchants,
        unique_cards=unique_cards,
    )


def compute_all_windows(
    transactions: list[dict[str, Any]],
    reference_timestamp: datetime | str | None = None,
) -> dict[int, WindowStats]:
    """Compute statistics for multiple time windows.

    Deduplicates by transaction_id so merged card/merchant histories do not double-count.
    """
    anchor = _coerce_datetime(reference_timestamp) or datetime.now(UTC)

    deduped: dict[str, dict[str, Any]] = {}
    for txn in transactions:
        txn_id = str(txn.get("transaction_id") or "")
        if txn_id:
            deduped[txn_id] = txn
            continue
        synthetic_key = (
            f"{txn.get('card_id', '')}|{txn.get('merchant_id', '')}|"
            f"{txn.get('transaction_timestamp', '')}|{txn.get('amount', '')}|{txn.get('status', '')}"
        )
        deduped[synthetic_key] = txn

    unique_transactions = list(deduped.values())
    windows = {}
    for hours in [1, 6, 24, 72]:
        window_txns = []
        cutoff = anchor - timedelta(hours=hours)
        for t in unique_transactions:
            ts = _coerce_datetime(t.get("transaction_timestamp"))
            if ts and cutoff <= ts <= anchor:
                window_txns.append(t)
        windows[hours] = compute_window_stats(window_txns, hours)
    return windows


def extract_signals(
    context: TransactionContext,
    window_stats: dict[int, WindowStats],
    rule_matches: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
) -> list[Signal]:
    """Extract signals from context and window statistics."""
    signals = []

    if context.amount > 500:
        signals.append(Signal("high_amount", True, 0.3))

    if context.velocity_score and context.velocity_score > 70:
        signals.append(Signal("high_velocity", True, 0.4))

    if context.fraud_score and context.fraud_score > 60:
        signals.append(Signal("high_fraud_score", True, 0.5))

    if window_stats.get(1) and window_stats[1].transaction_count > 5:
        signals.append(Signal("burst_1h", True, 0.5))

    if window_stats.get(24) and window_stats[24].decline_count > 3:
        signals.append(Signal("high_decline_rate", True, 0.4))

    if rule_matches:
        signals.append(Signal("has_rule_matches", len(rule_matches), 0.3))

    if reviews:
        signals.append(Signal("has_reviews", True, 0.2))

    if context.decline_reason:
        signals.append(Signal("decline_reason", context.decline_reason, 0.3))

    if context.amount > 1000:
        signals.append(Signal("high_amount", True, 0.5))

    round_numbers = [100, 200, 300, 400, 500, 750, 1000, 1500, 2000, 5000, 10000]
    if int(context.amount) in round_numbers:
        signals.append(Signal("round_number_amount", True, 0.3))

    return signals


def assemble_context(
    transaction: dict[str, Any],
    card_history: list[dict[str, Any]],
    merchant_history: list[dict[str, Any]],
    rule_matches: list[dict[str, Any]],
    reviews: list[dict[str, Any]],
    notes: list[dict[str, Any]],
    case: dict[str, Any] | None,
) -> dict[str, Any]:
    """Assemble complete context from raw data."""
    velocity_snapshot = transaction.get("velocity_snapshot")
    if velocity_snapshot is None:
        velocity_snapshot = {}

    tx_timestamp = _coerce_datetime(transaction.get("transaction_timestamp")) or datetime.now(UTC)

    ctx = TransactionContext(
        transaction_id=transaction.get("transaction_id", ""),
        amount=float(transaction.get("amount", 0.0) or 0.0),
        currency=transaction.get("currency", "USD"),
        merchant_id=transaction.get("merchant_id", ""),
        merchant_name=transaction.get("merchant_name", ""),
        card_id=transaction.get("card_id", ""),
        card_last_four=transaction.get("card_last_four", ""),
        transaction_timestamp=tx_timestamp,
        status=transaction.get("status", ""),
        decline_reason=transaction.get("decline_reason"),
        velocity_score=float(transaction.get("velocity_score") or 0) or None,
        fraud_score=float(transaction.get("fraud_score") or 0) or None,
    )

    all_txns = card_history + merchant_history
    windows = compute_all_windows(all_txns, reference_timestamp=ctx.transaction_timestamp)

    signals = extract_signals(ctx, windows, rule_matches, reviews)

    return {
        "transaction_id": transaction.get("transaction_id", ""),
        "transaction": ctx,
        "transaction_pk_id": transaction.get("id", ""),
        "velocity_snapshot": velocity_snapshot,
        "transaction_context": transaction.get("transaction_context") or {},
        "windows": windows,
        "signals": signals,
        "rule_matches": rule_matches,
        "reviews": reviews,
        "notes": notes,
        "case": case,
        "card_history": card_history,
    }


def compute_context_features(
    context: dict[str, Any],
    windows: dict[int, WindowStats],
    card_history: list[dict[str, Any]],
    merchant_history: list[dict[str, Any]],
    transaction: dict[str, Any],
    transaction_context: dict[str, Any],
    velocity_snapshot: dict[str, Any],
) -> dict[str, Any]:
    """Compute deterministic feature pack from context data.

    This creates a stable feature set that tools and prompts can rely on,
    ensuring consistent behavior across invocations.
    """
    tx_timestamp = _coerce_datetime(transaction.get("transaction_timestamp"))

    all_txns = card_history + merchant_history
    txn_count_5m = _count_txns_since(all_txns, tx_timestamp, minutes=5) if tx_timestamp else 0
    txn_count_1h = windows.get(1).transaction_count if windows.get(1) else 0
    txn_count_24h = windows.get(24).transaction_count if windows.get(24) else 0

    decline_rate_1h = _compute_decline_rate(windows.get(1)) if windows.get(1) else 0.0
    avg_amount_30d = _compute_avg_amount(all_txns, days=30, ref_timestamp=tx_timestamp)
    amount_zscore = _compute_amount_zscore(all_txns, transaction.get("amount", 0), tx_timestamp)

    distinct_merchants_1h = windows.get(1).unique_merchants if windows.get(1) else 0
    distinct_cards_1h = windows.get(1).unique_cards if windows.get(1) else 0

    device_info = transaction_context.get("device") or {}
    ip_info = transaction_context.get("ip_geolocation") or {}

    features: dict[str, Any] = {
        "transaction_id": transaction.get("transaction_id"),
        "amount": transaction.get("amount"),
        "currency": transaction.get("currency", "USD"),
        "decision": transaction.get("status"),
        "mcc": transaction.get("merchant_category"),
        "timestamp": transaction.get("transaction_timestamp"),
        "card_id": transaction.get("card_id"),
        "merchant_id": transaction.get("merchant_id"),
        "txn_count_5m": txn_count_5m,
        "txn_count_1h": txn_count_1h,
        "txn_count_24h": txn_count_24h,
        "decline_rate_1h": decline_rate_1h,
        "avg_amount_30d": avg_amount_30d,
        "amount_zscore": amount_zscore,
        "distinct_merchants_1h": distinct_merchants_1h,
        "distinct_cards_1h": distinct_cards_1h,
        "transaction_context": transaction_context,
        "velocity_snapshot": velocity_snapshot,
        "velocity_results": velocity_snapshot.get("velocity_results"),
        "engine_metadata": transaction_context.get("engine_metadata"),
        "ip_address": ip_info.get("ip_address"),
        "ip_country_alpha3": ip_info.get("country_alpha3"),
        "device_id": device_info.get("device_id"),
        "device_fingerprint_hash": device_info.get("device_fingerprint_hash"),
    }

    return features


def _count_txns_since(transactions: list[dict[str, Any]], reference: datetime, minutes: int) -> int:
    """Count transactions within N minutes of reference timestamp."""
    if not transactions or not reference:
        return 0
    cutoff = reference - timedelta(minutes=minutes)
    count = 0
    for t in transactions:
        ts = _coerce_datetime(t.get("transaction_timestamp"))
        if ts and cutoff <= ts <= reference:
            count += 1
    return count


def _compute_decline_rate(window_stats: WindowStats | None) -> float:
    """Compute decline rate as percentage."""
    if not window_stats or window_stats.transaction_count == 0:
        return 0.0
    return (window_stats.decline_count / window_stats.transaction_count) * 100


def _compute_avg_amount(
    transactions: list[dict[str, Any]], days: int, ref_timestamp: datetime | None
) -> float:
    """Compute average transaction amount over time window."""
    if not transactions or not ref_timestamp:
        return 0.0
    cutoff = ref_timestamp - timedelta(days=days)
    amounts = []
    for t in transactions:
        ts = _coerce_datetime(t.get("transaction_timestamp"))
        if ts and cutoff <= ts <= ref_timestamp:
            amt = t.get("amount")
            if amt is not None:
                try:
                    amounts.append(float(amt))
                except TypeError, ValueError:
                    pass
    return sum(amounts) / len(amounts) if amounts else 0.0


def _compute_amount_zscore(
    transactions: list[dict[str, Any]], current_amount: Any, ref_timestamp: datetime | None
) -> float | None:
    """Compute z-score of current amount vs 30-day history."""
    if not transactions or not ref_timestamp:
        return None
    try:
        current_amount_value = float(current_amount)
    except TypeError, ValueError:
        return None
    cutoff = ref_timestamp - timedelta(days=30)
    amounts = []
    for t in transactions:
        ts = _coerce_datetime(t.get("transaction_timestamp"))
        if ts and cutoff <= ts <= ref_timestamp:
            amt = t.get("amount")
            if amt is not None:
                try:
                    amounts.append(float(amt))
                except TypeError, ValueError:
                    pass
    if len(amounts) < 3:
        return None
    mean = sum(amounts) / len(amounts)
    variance = sum((x - mean) ** 2 for x in amounts) / len(amounts)
    std = variance**0.5
    if std == 0:
        return None
    return (current_amount_value - mean) / std
