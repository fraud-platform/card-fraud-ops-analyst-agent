"""Helpers for reading similarity results in a consistent shape."""

from __future__ import annotations

from typing import Any


def get_similarity_score(similarity: Any) -> float:
    """Extract overall similarity score from dict/object payloads."""
    if similarity is None:
        return 0.0
    if isinstance(similarity, dict):
        nested = similarity.get("similarity_result")
        if nested is not None:
            return float(getattr(nested, "overall_score", 0.0))
        return float(similarity.get("overall_score", 0.0))
    return float(getattr(similarity, "overall_score", 0.0))


def get_similarity_match_count(similarity: Any) -> int:
    """Extract match count from dict/object payloads."""
    if similarity is None:
        return 0
    if isinstance(similarity, dict):
        nested = similarity.get("similarity_result")
        if nested is not None:
            matches = getattr(nested, "matches", [])
        else:
            matches = similarity.get("matches", [])
    else:
        matches = getattr(similarity, "matches", [])
    return len(matches) if isinstance(matches, list) else 0
