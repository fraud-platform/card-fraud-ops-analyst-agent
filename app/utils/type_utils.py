"""Type conversion utilities for normalizing values across the codebase."""

from __future__ import annotations

from decimal import Decimal
from typing import Any


def to_float(value: Any, default: float = 0.0) -> float:
    """Convert a value to float with comprehensive type handling.

    Handles float, int, Decimal explicitly before attempting conversion,
    providing better performance and clearer intent than a bare try/except.

    Args:
        value: The value to convert to float
        default: The default value if conversion fails

    Returns:
        The converted float value or the default
    """
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except TypeError, ValueError:
        return default
