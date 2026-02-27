"""Helpers for mixed dict/object payload access used across tools."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def get_attr(value: Any, key: str, default: Any = None) -> Any:
    """Read key from mapping-like values or attribute from objects."""
    if isinstance(value, Mapping):
        return value.get(key, default)
    return getattr(value, key, default)


def as_dict(value: Any) -> dict[str, Any]:
    """Return value when it is a dict; otherwise an empty dict."""
    return value if isinstance(value, dict) else {}


def as_list(value: Any) -> list[Any]:
    """Return value when it is a list; otherwise an empty list."""
    return value if isinstance(value, list) else []
