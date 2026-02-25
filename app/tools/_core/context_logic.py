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
