"""Unit tests for pattern engine core module."""

from datetime import UTC, datetime, timedelta
from decimal import Decimal

from app.agents.context_builder_core import Signal, WindowStats
from app.agents.pattern_engine_core import (
    PatternScore,
    _calculate_mean,
    _calculate_std_dev,
    _get_hour_from_timestamp,
    _get_merchant_category_risk,
    _is_round_number,
    _is_unusual_hour,
    compute_severity,
    run_pattern_scoring,
    score_amount_anomalies,
    score_card_testing,
    score_cross_merchant_patterns,
    score_decline_anomalies,
    score_time_anomalies,
    score_velocity_patterns,
)


def test_is_round_number_exact():
    """Test exact round numbers."""
    assert _is_round_number(100.0) is True
    assert _is_round_number(500.0) is True
    assert _is_round_number(1000.0) is True
    assert _is_round_number(10000.0) is True


def test_is_round_number_with_cents():
    """Test round numbers with whole dollar amounts."""
    assert _is_round_number(100.0) is True
    assert _is_round_number(500.0) is True
    assert _is_round_number(1000.0) is True


def test_is_round_number_not_fraud_amounts():
    """Test amounts that are not common fraud round numbers."""
    assert _is_round_number(42.50) is False
    assert _is_round_number(123.45) is False
    assert _is_round_number(77.77) is False


def test_is_round_number_zero_negative():
    """Test zero and negative amounts."""
    assert _is_round_number(0.0) is False
    assert _is_round_number(-100.0) is False


def test_calculate_mean():
    """Test mean calculation."""
    assert _calculate_mean([10, 20, 30]) == 20.0
    assert _calculate_mean([100]) == 100.0
    assert _calculate_mean([]) == 0.0


def test_calculate_std_dev():
    """Test standard deviation calculation."""
    values = [2.0, 4.0, 4.0, 4.0, 5.0, 5.0, 7.0, 9.0]
    mean = _calculate_mean(values)
    std = _calculate_std_dev(values, mean)
    assert 1.8 < std < 2.5


def test_calculate_std_dev_insufficient_data():
    """Test std dev with insufficient data."""
    assert _calculate_std_dev([], 0) == 0.0
    assert _calculate_std_dev([10], 10) == 0.0


def test_score_amount_anomalies_round_number():
    """Test amount anomaly detection for round numbers."""
    transaction = {"amount": 500.0}
    result = score_amount_anomalies(transaction, [], {})
    assert result.pattern_name == "amount_anomaly"
    assert result.score > 0
    assert result.details.get("round_number") is True


def test_score_amount_anomalies_high_amount():
    """Test amount anomaly detection for high amounts."""
    transaction = {"amount": 1500.0}
    result = score_amount_anomalies(transaction, [], {})
    assert result.score > 0
    assert "high_amount" in result.details or "elevated_amount" in result.details


def test_score_amount_anomalies_statistical_outlier():
    """Test amount anomaly detection for statistical outliers."""
    transaction = {"amount": 1000.0}
    card_history = [
        {"amount": 50.0},
        {"amount": 60.0},
        {"amount": 55.0},
        {"amount": 45.0},
        {"amount": 50.0},
    ]
    result = score_amount_anomalies(transaction, card_history, {})
    assert result.details.get("outlier") is True


def test_score_amount_anomalies_normal_amount():
    """Test amount anomaly detection returns low score for normal amounts."""
    transaction = {"amount": 50.0}
    card_history = [
        {"amount": 40.0},
        {"amount": 50.0},
        {"amount": 45.0},
    ]
    result = score_amount_anomalies(transaction, card_history, {})
    assert result.score == 0.0


def test_score_amount_anomalies_none_transaction():
    """Test amount anomaly with None transaction."""
    result = score_amount_anomalies(None, [], {})
    assert result.score == 0.0


def test_score_amount_anomalies_with_window_avg():
    """Test amount spike vs 24h average."""
    transaction = {"amount": 300.0}
    window_stats = {
        24: WindowStats(24, 10, 300.0, 0, 5, 1),
    }
    result = score_amount_anomalies(transaction, [], window_stats)
    assert "spike_vs_avg" in result.details


def test_score_amount_anomalies_with_decimal_window_avg():
    """Window totals may come back as Decimal from DB adapters."""
    transaction = {"amount": 300.0}
    window_stats = {
        24: WindowStats(24, 10, Decimal("300.0"), 0, 5, 1),
    }
    result = score_amount_anomalies(transaction, [], window_stats)
    assert "spike_vs_avg" in result.details


def test_score_amount_anomalies_custom_thresholds():
    """Test round number detection with custom thresholds."""
    assert _is_round_number(250.0, [250, 500, 750]) is True
    assert _is_round_number(500.0, [250, 500, 750]) is True
    assert _is_round_number(100.0, [250, 500, 750]) is False


def test_score_velocity_patterns_burst():
    window_stats = {
        1: WindowStats(1, 15, 1000.0, 0, 5, 1),
        6: WindowStats(6, 25, 2000.0, 0, 8, 2),
    }
    signals = [Signal("burst_1h", True, 0.5)]
    result = score_velocity_patterns(window_stats, signals)
    assert result.pattern_name == "velocity"
    assert result.score > 0.6


def test_score_velocity_patterns_no_burst():
    window_stats = {
        1: WindowStats(1, 2, 100.0, 0, 2, 1),
    }
    signals = []
    result = score_velocity_patterns(window_stats, signals)
    assert result.score == 0.0


def test_score_decline_anomalies_high():
    window_stats = {
        24: WindowStats(24, 10, 1000.0, 6, 5, 2),
    }
    signals = []
    result = score_decline_anomalies(window_stats, signals)
    assert result.score > 0.5


def test_score_decline_anomalies_low():
    window_stats = {
        24: WindowStats(24, 10, 1000.0, 1, 5, 2),
    }
    signals = []
    result = score_decline_anomalies(window_stats, signals)
    assert result.score == 0.0


def test_score_cross_merchant_patterns():
    window_stats = {
        24: WindowStats(24, 15, 1500.0, 0, 12, 3),
    }
    result = score_cross_merchant_patterns(window_stats, None)
    assert result.pattern_name == "cross_merchant"
    assert result.score > 0.5


def test_run_pattern_scoring():
    context = {
        "windows": {
            1: WindowStats(1, 12, 1000.0, 0, 5, 1),
            24: WindowStats(24, 15, 1500.0, 8, 10, 3),
        },
        "signals": [Signal("burst_1h", True, 0.5)],
        "transaction": None,
        "card_history": [],
        "transaction_context": {},
    }
    scores = run_pattern_scoring(context)
    assert len(scores) == 6
    pattern_names = [s.pattern_name for s in scores]
    assert "amount_anomaly" in pattern_names
    assert "time_anomaly" in pattern_names
    assert "velocity" in pattern_names
    assert "decline_anomaly" in pattern_names
    assert "cross_merchant" in pattern_names
    assert "card_testing" in pattern_names


def test_compute_severity_critical():
    scores = [
        PatternScore("velocity", 0.9, 0.4, {}),
        PatternScore("decline", 0.8, 0.3, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "CRITICAL"


def test_compute_severity_high():
    scores = [
        PatternScore("velocity", 0.6, 0.4, {}),
        PatternScore("decline", 0.5, 0.3, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "HIGH"


def test_compute_severity_medium():
    scores = [
        PatternScore("velocity", 0.4, 0.4, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "MEDIUM"


def test_compute_severity_low():
    scores = [
        PatternScore("velocity", 0.1, 0.4, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "LOW"


def test_compute_severity_isolated_time_signal_stays_low():
    """Single time anomaly signal should remain advisory (LOW)."""
    scores = [
        PatternScore("amount_anomaly", 0.0, 0.35, {}),
        PatternScore("time_anomaly", 0.4, 0.25, {"unusual_hour": 2}),
        PatternScore("velocity", 0.0, 0.4, {}),
        PatternScore("decline_anomaly", 0.0, 0.3, {}),
        PatternScore("cross_merchant", 0.0, 0.3, {}),
        PatternScore("card_testing", 0.0, 0.35, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "LOW"


def test_compute_severity_promotes_concentrated_strong_signals():
    """Strong fraud signals should not be diluted by multiple zero-score patterns."""
    scores = [
        PatternScore("amount_anomaly", 0.0, 0.35, {}),
        PatternScore("time_anomaly", 0.0, 0.25, {}),
        PatternScore("velocity", 0.0, 0.4, {}),
        PatternScore("decline_anomaly", 0.9, 0.3, {}),
        PatternScore("cross_merchant", 0.0, 0.3, {}),
        PatternScore("card_testing", 0.7, 0.35, {}),
    ]
    severity = compute_severity(scores)
    assert severity == "HIGH"


def test_compute_severity_empty():
    severity = compute_severity([])
    assert severity == "LOW"


def test_get_hour_from_timestamp_datetime():
    """Test extracting hour from datetime object."""
    ts = datetime(2024, 1, 15, 3, 30, 0, tzinfo=UTC)
    assert _get_hour_from_timestamp(ts) == 3


def test_get_hour_from_timestamp_string():
    """Test extracting hour from ISO string."""
    assert _get_hour_from_timestamp("2024-01-15T03:30:00Z") == 3
    assert _get_hour_from_timestamp("2024-01-15T14:45:00+00:00") == 14


def test_get_hour_from_timestamp_none():
    """Test None timestamp returns None."""
    assert _get_hour_from_timestamp(None) is None


def test_is_unusual_hour():
    """Test unusual hour detection (late night/early morning)."""
    assert _is_unusual_hour(0) is True
    assert _is_unusual_hour(2) is True
    assert _is_unusual_hour(5) is True
    assert _is_unusual_hour(6) is False
    assert _is_unusual_hour(12) is False
    assert _is_unusual_hour(18) is False
    assert _is_unusual_hour(23) is False


def test_get_merchant_category_risk():
    """Test merchant category risk classification."""
    assert _get_merchant_category_risk("7999") == "high"
    assert _get_merchant_category_risk("5812") == "high"
    assert _get_merchant_category_risk("5411") == "medium"
    assert _get_merchant_category_risk("5541") == "medium"
    assert _get_merchant_category_risk("1234") == "low"
    assert _get_merchant_category_risk(None) == "low"


def test_score_time_anomalies_unusual_hour():
    """Test time anomaly detection for unusual hours."""
    transaction = {"transaction_timestamp": datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)}
    result = score_time_anomalies(transaction, [], {})
    assert result.pattern_name == "time_anomaly"
    assert result.score > 0
    assert result.details.get("unusual_hour") == 3


def test_score_time_anomalies_normal_hour():
    """Test time anomaly returns low score for normal hours."""
    transaction = {"transaction_timestamp": datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)}
    result = score_time_anomalies(transaction, [], {})
    assert result.score == 0.0


def test_score_time_anomalies_timezone_mismatch():
    """Test timezone mismatch detection."""
    transaction = {"transaction_timestamp": datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)}
    context = {"ip_country": "US", "card_country": "CN"}
    result = score_time_anomalies(transaction, [], context)
    assert result.score > 0
    assert result.details.get("timezone_mismatch") is True


def test_score_time_anomalies_high_risk_combo():
    """Test high-risk merchant + unusual hour combo."""
    transaction = {
        "transaction_timestamp": datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC),
        "merchant_category_code": "7999",
    }
    result = score_time_anomalies(transaction, [], {})
    assert result.score > 0
    assert result.details.get("high_risk_combo") is True


def test_score_time_anomalies_unusual_for_cardholder():
    """Test unusual hour for cardholder history."""
    transaction = {"transaction_timestamp": datetime(2024, 1, 15, 14, 0, 0, tzinfo=UTC)}
    card_history = [
        {"transaction_timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)},
        {"transaction_timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)},
        {"transaction_timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)},
        {"transaction_timestamp": datetime(2024, 1, 15, 11, 0, 0, tzinfo=UTC)},
        {"transaction_timestamp": datetime(2024, 1, 15, 10, 0, 0, tzinfo=UTC)},
    ]
    result = score_time_anomalies(transaction, card_history, {})
    assert result.details.get("unusual_hour_for_cardholder") is True


def test_score_time_anomalies_none_transaction():
    """Test time anomaly with None transaction."""
    result = score_time_anomalies(None, [], {})
    assert result.score == 0.0


def test_run_pattern_scoring_includes_time():
    """Test run_pattern_scoring includes time_anomaly pattern."""
    context = {
        "windows": {},
        "signals": [],
        "transaction": {"transaction_timestamp": datetime(2024, 1, 15, 3, 0, 0, tzinfo=UTC)},
        "card_history": [],
        "transaction_context": {},
    }
    scores = run_pattern_scoring(context)
    pattern_names = [s.pattern_name for s in scores]
    assert "time_anomaly" in pattern_names


def test_score_card_testing_empty_history():
    """Test card testing with empty history returns zero score."""
    transaction = {"amount": 50.0}
    result = score_card_testing(transaction, [])
    assert result.pattern_name == "card_testing"
    assert result.score == 0.0


def test_score_card_testing_increasing_sequence():
    """Test card testing detection for increasing amount sequence."""
    now = datetime.now(UTC)
    transaction = {"amount": 25.0, "transaction_timestamp": now}
    card_history = [
        {"amount": 5.0, "transaction_timestamp": now - timedelta(minutes=15), "status": "APPROVE"},
        {"amount": 10.0, "transaction_timestamp": now - timedelta(minutes=10), "status": "APPROVE"},
        {"amount": 15.0, "transaction_timestamp": now - timedelta(minutes=5), "status": "APPROVE"},
    ]
    result = score_card_testing(transaction, card_history)
    assert result.score > 0
    assert result.details.get("increasing_sequence") is True


def test_score_card_testing_requires_chronological_increase():
    """Amount ladders must increase over time, not just by sorted values."""
    now = datetime.now(UTC)
    transaction = {"amount": 12.0, "transaction_timestamp": now}
    card_history = [
        {"amount": 20.0, "transaction_timestamp": now - timedelta(minutes=15), "status": "APPROVE"},
        {"amount": 5.0, "transaction_timestamp": now - timedelta(minutes=10), "status": "APPROVE"},
        {"amount": 15.0, "transaction_timestamp": now - timedelta(minutes=5), "status": "APPROVE"},
    ]
    result = score_card_testing(transaction, card_history)
    assert result.details.get("increasing_sequence") is not True


def test_score_card_testing_high_decline_rate():
    """Test card testing detection for high decline rate."""
    now = datetime.now(UTC)
    transaction = {"amount": 5.0, "transaction_timestamp": now}
    card_history = [
        {"amount": 5.0, "transaction_timestamp": now - timedelta(minutes=5), "status": "DECLINE"},
        {"amount": 10.0, "transaction_timestamp": now - timedelta(minutes=10), "status": "DECLINE"},
        {"amount": 15.0, "transaction_timestamp": now - timedelta(minutes=15), "status": "APPROVE"},
    ]
    result = score_card_testing(transaction, card_history)
    assert result.score > 0
    assert result.details.get("high_decline_rate") is True


def test_score_card_testing_multiple_merchants():
    """Test card testing detection for multiple merchants."""
    now = datetime.now(UTC)
    transaction = {"amount": 5.0, "transaction_timestamp": now, "merchant_id": "m3"}
    card_history = [
        {"amount": 5.0, "transaction_timestamp": now - timedelta(minutes=5), "merchant_id": "m1"},
        {"amount": 10.0, "transaction_timestamp": now - timedelta(minutes=10), "merchant_id": "m2"},
    ]
    result = score_card_testing(transaction, card_history)
    assert result.details.get("multiple_merchants") is True


def test_score_card_testing_small_amount_sequence():
    """Test card testing detection for small amount sequence."""
    now = datetime.now(UTC)
    transaction = {"amount": 5.0, "transaction_timestamp": now}
    card_history = [
        {"amount": 3.0, "transaction_timestamp": now - timedelta(minutes=5)},
        {"amount": 2.0, "transaction_timestamp": now - timedelta(minutes=10)},
    ]
    result = score_card_testing(transaction, card_history)
    assert result.details.get("small_amount_sequence") is True


def test_run_pattern_scoring_includes_card_testing():
    """Test run_pattern_scoring includes card_testing pattern."""
    now = datetime.now(UTC)
    context = {
        "windows": {},
        "signals": [],
        "transaction": {"amount": 25.0, "transaction_timestamp": now},
        "card_history": [
            {"amount": 5.0, "transaction_timestamp": now - timedelta(minutes=5)},
            {"amount": 10.0, "transaction_timestamp": now - timedelta(minutes=10)},
            {"amount": 15.0, "transaction_timestamp": now - timedelta(minutes=15)},
        ],
        "transaction_context": {},
    }
    scores = run_pattern_scoring(context)
    pattern_names = [s.pattern_name for s in scores]
    assert "card_testing" in pattern_names
