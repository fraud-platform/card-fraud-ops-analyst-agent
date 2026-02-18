"""Unit tests for freshness weighting module."""

from datetime import UTC, datetime, timedelta

import pytest

from app.agents.freshness import (
    FRESHNESS_CONFIG,
    FreshnessConfig,
    apply_freshness_to_matches,
    compute_freshness_weight,
    exponential_decay_weight,
    get_freshness_config,
)


class TestExponentialDecayWeight:
    def test_very_recent_transaction_returns_max(self):
        recent = datetime.now(UTC) - timedelta(minutes=5)
        weight = exponential_decay_weight(recent, half_life_hours=24.0)
        assert weight > 0.99  # Almost max

    def test_old_transaction_returns_min(self):
        old = datetime.now(UTC) - timedelta(days=30)
        weight = exponential_decay_weight(old, half_life_hours=24.0, min_weight=0.1)
        assert weight == pytest.approx(0.1, abs=1e-6)

    def test_none_timestamp_returns_0_5(self):
        weight = exponential_decay_weight(None)
        assert weight == 0.5

    def test_future_timestamp_returns_max(self):
        future = datetime.now(UTC) + timedelta(hours=1)
        weight = exponential_decay_weight(future, max_weight=1.0)
        assert weight == 1.0

    def test_half_life_at_24h(self):
        """After one half-life, weight should be ~50% of max."""
        ts = datetime.now(UTC) - timedelta(hours=24)
        weight = exponential_decay_weight(ts, half_life_hours=24.0, max_weight=1.0, min_weight=0.0)
        assert abs(weight - 0.5) < 0.05

    def test_weight_between_min_and_max(self):
        ts = datetime.now(UTC) - timedelta(hours=12)
        weight = exponential_decay_weight(ts, half_life_hours=24.0, max_weight=1.0, min_weight=0.2)
        assert 0.2 <= weight <= 1.0

    def test_custom_min_weight_floor(self):
        very_old = datetime.now(UTC) - timedelta(days=365)
        weight = exponential_decay_weight(very_old, half_life_hours=24.0, min_weight=0.3)
        assert weight == pytest.approx(0.3, abs=1e-6)

    def test_iso_string_timestamp_is_supported(self):
        recent_iso = (datetime.now(UTC) - timedelta(minutes=5)).isoformat().replace("+00:00", "Z")
        weight = exponential_decay_weight(recent_iso, half_life_hours=24.0)
        assert weight > 0.99


class TestGetFreshnessConfig:
    def test_known_evidence_type_pattern_velocity(self):
        config = get_freshness_config("pattern_velocity")
        assert isinstance(config, FreshnessConfig)
        assert config.half_life_hours == 6.0

    def test_known_evidence_type_similarity_vector(self):
        config = get_freshness_config("similarity_vector")
        assert config.half_life_hours == 72.0

    def test_known_evidence_type_counter_evidence_3ds(self):
        config = get_freshness_config("counter_evidence_3ds")
        assert config.half_life_hours == 168.0

    def test_unknown_evidence_type_falls_back_to_default(self):
        config = get_freshness_config("nonexistent_type")
        assert config.half_life_hours == FRESHNESS_CONFIG["default"]["half_life_hours"]

    def test_all_configured_types_return_valid_config(self):
        for evidence_type in FRESHNESS_CONFIG:
            config = get_freshness_config(evidence_type)
            assert config.half_life_hours > 0
            assert 0.0 <= config.min_weight <= config.max_weight <= 1.0


class TestComputeFreshnessWeight:
    def test_recent_pattern_velocity_high_weight(self):
        recent = datetime.now(UTC) - timedelta(minutes=30)
        weight = compute_freshness_weight("pattern_velocity", recent)
        assert weight > 0.9

    def test_old_pattern_velocity_min_weight(self):
        old = datetime.now(UTC) - timedelta(days=7)
        weight = compute_freshness_weight("pattern_velocity", old)
        assert weight == pytest.approx(FRESHNESS_CONFIG["pattern_velocity"]["min_weight"], abs=1e-6)

    def test_none_timestamp_returns_0_5(self):
        weight = compute_freshness_weight("pattern_velocity", None)
        assert weight == 0.5

    def test_similarity_vector_longer_half_life(self):
        ts = datetime.now(UTC) - timedelta(hours=24)
        velocity_weight = compute_freshness_weight("pattern_velocity", ts)
        vector_weight = compute_freshness_weight("similarity_vector", ts)
        # similarity_vector has longer half-life → decays slower → higher weight after same time
        assert vector_weight > velocity_weight


class TestApplyFreshnessToMatches:
    def test_empty_matches_returns_empty(self):
        result = apply_freshness_to_matches([])
        assert result == []

    def test_adds_freshness_weight_to_details(self):
        recent = datetime.now(UTC) - timedelta(minutes=10)
        matches = [
            {"transaction_id": "abc", "similarity_score": 0.8, "transaction_timestamp": recent}
        ]
        result = apply_freshness_to_matches(matches, evidence_type="similarity_attribute")
        assert len(result) == 1
        assert "freshness_weight" in result[0]["details"]
        assert result[0]["details"]["freshness_weight"] > 0.0

    def test_similarity_score_reduced_by_freshness(self):
        old = datetime.now(UTC) - timedelta(days=90)
        matches = [{"transaction_id": "abc", "similarity_score": 1.0, "transaction_timestamp": old}]
        result = apply_freshness_to_matches(matches, evidence_type="similarity_attribute")
        assert result[0]["similarity_score"] < 1.0

    def test_none_timestamp_uses_half_weight(self):
        matches = [
            {"transaction_id": "abc", "similarity_score": 0.8, "transaction_timestamp": None}
        ]
        result = apply_freshness_to_matches(matches)
        # freshness=0.5 → score = 0.8 * 0.5 = 0.4
        assert abs(result[0]["similarity_score"] - 0.4) < 0.01

    def test_preserves_other_match_fields(self):
        ts = datetime.now(UTC)
        matches = [
            {
                "transaction_id": "xyz",
                "similarity_score": 0.5,
                "transaction_timestamp": ts,
                "match_type": "vector",
            }
        ]
        result = apply_freshness_to_matches(matches)
        assert result[0]["transaction_id"] == "xyz"
        assert result[0]["match_type"] == "vector"
