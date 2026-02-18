"""Unit tests for clock utility."""

from datetime import UTC, datetime

from app.utils.clock import utc_now


def test_utc_now():
    result = utc_now()
    assert isinstance(result, datetime)
    assert result.tzinfo is not None


def test_utc_now_returns_utc():
    result = utc_now()
    # Check it's close to now
    now = datetime.now(UTC)
    diff = abs((result - now).total_seconds())
    assert diff < 5  # Within 5 seconds
