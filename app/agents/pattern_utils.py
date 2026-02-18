"""Helpers for working with normalized pattern analysis payloads."""

from typing import Any


def to_pattern_dicts(pattern_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
    """Return pattern scores as normalized dict objects.

    Supports both:
    - `{"patterns": [{"pattern_name": ..., "score": ...}, ...]}`
    - `{"pattern_scores": [PatternScore(...), ...]}`
    """
    if not pattern_analysis:
        return []

    patterns = pattern_analysis.get("patterns")
    if isinstance(patterns, list):
        return [p for p in patterns if isinstance(p, dict)]

    pattern_scores = pattern_analysis.get("pattern_scores") or []
    out: list[dict[str, Any]] = []
    for score in pattern_scores:
        if isinstance(score, dict):
            out.append(score)
        else:
            out.append(
                {
                    "pattern_name": getattr(score, "pattern_name", "unknown"),
                    "score": float(getattr(score, "score", 0.0)),
                    "details": getattr(score, "details", {}) or {},
                }
            )
    return out
