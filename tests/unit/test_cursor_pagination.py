"""Unit tests for cursor pagination."""

from app.persistence.base import BaseCursor


def test_cursor_encode_decode():
    cursor = BaseCursor({"status": "OPEN", "created_at": "2026-01-01T00:00:00Z"})
    encoded = cursor.encode()
    decoded = BaseCursor.decode(encoded)
    assert decoded.values == cursor.values


def test_cursor_decode_optional():
    cursor = BaseCursor.decode_optional(None)
    assert cursor is None


def test_cursor_roundtrip():
    original = BaseCursor({"id": "123", "ts": "2026-01-01"})
    encoded = original.encode()
    decoded = BaseCursor.decode(encoded)
    assert decoded.values == original.values


def test_cursor_different_values():
    cursor1 = BaseCursor({"status": "OPEN"})
    cursor2 = BaseCursor({"status": "CLOSED"})
    assert cursor1.encode() != cursor2.encode()
