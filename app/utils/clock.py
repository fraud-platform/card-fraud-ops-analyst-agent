"""Clock utility for testability."""

from datetime import UTC, datetime


def utc_now() -> datetime:
    """Return current UTC time. Override in tests."""
    return datetime.now(UTC)
