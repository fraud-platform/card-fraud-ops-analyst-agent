"""Unit tests for context builder core module."""

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.context_builder_core import (
    Signal,
    TransactionContext,
    WindowStats,
    compute_all_windows,
    compute_window_stats,
    extract_signals,
)


def test_compute_window_stats_empty():
    stats = compute_window_stats([], 24)
    assert stats.window_hours == 24
    assert stats.transaction_count == 0
    assert stats.total_amount == 0.0


def test_compute_window_stats_with_data():
    transactions = [
        {"amount": 100.0, "status": "APPROVED", "merchant_id": "m1", "card_id": "c1"},
        {"amount": 200.0, "status": "DECLINED", "merchant_id": "m1", "card_id": "c1"},
    ]
    stats = compute_window_stats(transactions, 24)
    assert stats.transaction_count == 2
    assert stats.total_amount == 300.0
    assert stats.decline_count == 1
    assert stats.unique_merchants == 1
    assert stats.unique_cards == 1


def test_compute_all_windows():
    anchor = datetime.now(UTC)
    transactions = [
        {
            "amount": 100.0,
            "transaction_timestamp": anchor - timedelta(minutes=30),
            "status": "APPROVED",
            "merchant_id": "m1",
            "card_id": "c1",
        },
    ]
    windows = compute_all_windows(transactions, reference_timestamp=anchor)
    assert 1 in windows
    assert 6 in windows
    assert 24 in windows
    assert 72 in windows
    assert windows[1].transaction_count == 1


def test_compute_all_windows_uses_reference_timestamp_and_excludes_future():
    anchor = datetime(2026, 2, 1, 12, 0, tzinfo=UTC)
    transactions = [
        {
            "amount": 10.0,
            "transaction_timestamp": anchor - timedelta(minutes=30),
            "status": "APPROVED",
            "merchant_id": "m1",
            "card_id": "c1",
        },
        {
            "amount": 20.0,
            "transaction_timestamp": anchor - timedelta(hours=4),
            "status": "DECLINED",
            "merchant_id": "m2",
            "card_id": "c1",
        },
        {
            "amount": 30.0,
            "transaction_timestamp": anchor + timedelta(minutes=5),
            "status": "APPROVED",
            "merchant_id": "m3",
            "card_id": "c1",
        },
    ]

    windows = compute_all_windows(transactions, reference_timestamp=anchor)

    assert windows[1].transaction_count == 1
    assert windows[6].transaction_count == 2
    assert windows[24].transaction_count == 2


def test_extract_signals():
    ctx = TransactionContext(
        transaction_id="tx-1",
        amount=600.0,
        currency="USD",
        merchant_id="m1",
        merchant_name="Test Merchant",
        card_id="c1",
        card_last_four="1234",
        transaction_timestamp=datetime.now(UTC),
        status="DECLINED",
        decline_reason="insufficient_funds",
        velocity_score=80.0,
        fraud_score=70.0,
    )
    window_stats = {
        1: WindowStats(1, 10, 1000.0, 2, 3, 2),
        24: WindowStats(24, 50, 10000.0, 20, 10, 5),
    }
    signals = extract_signals(ctx, window_stats, [], [])
    signal_names = [s.name for s in signals]
    assert "high_amount" in signal_names
    assert "high_velocity" in signal_names
    assert "high_fraud_score" in signal_names
    assert "burst_1h" in signal_names
    assert "high_decline_rate" in signal_names


def test_transaction_context_immutable():
    ctx = TransactionContext(
        transaction_id="tx-1",
        amount=100.0,
        currency="USD",
        merchant_id="m1",
        merchant_name="Test",
        card_id="c1",
        card_last_four="1234",
        transaction_timestamp=datetime.now(UTC),
        status="APPROVED",
        decline_reason=None,
        velocity_score=None,
        fraud_score=None,
    )
    with pytest.raises(AttributeError):
        ctx.amount = 200.0


def test_signal_immutable():
    signal = Signal("test", "value", 0.5)
    with pytest.raises(AttributeError):
        signal.name = "changed"
