"""Utilities for converting dataclasses to plain dicts."""

from __future__ import annotations

from dataclasses import asdict, is_dataclass
from typing import Any


def to_dict(obj: Any) -> dict[str, Any]:
    """Convert a dataclass (possibly nested) to a JSON-friendly dict."""
    if isinstance(obj, dict):
        return obj
    if is_dataclass(obj) and not isinstance(obj, type):
        # asdict() recursively converts nested dataclasses.
        return asdict(obj)
    return {}


def to_dict_list(items: list[Any]) -> list[dict[str, Any]]:
    """Convert a list of dataclasses to plain dictionaries."""
    return [to_dict(item) for item in items]
