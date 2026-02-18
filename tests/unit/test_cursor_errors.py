"""Unit tests for base cursor with error handling."""

import pytest

from app.persistence.base import BaseCursor, CursorDecodeError


def test_cursor_encode_decode():
    cursor = BaseCursor({"status": "OPEN", "created_at": "2026-01-01T00:00:00Z"})
    encoded = cursor.encode()
    decoded = BaseCursor.decode(encoded)
    assert decoded.values == cursor.values


def test_cursor_decode_invalid():
    with pytest.raises(CursorDecodeError):
        BaseCursor.decode("invalid-base64!!!")


def test_cursor_decode_optional_invalid():
    result = BaseCursor.decode_optional("invalid!!!")
    assert result is None


def test_cursor_roundtrip():
    original = BaseCursor({"id": "123", "ts": "2026-01-01"})
    encoded = original.encode()
    decoded = BaseCursor.decode(encoded)
    assert decoded.values == original.values
