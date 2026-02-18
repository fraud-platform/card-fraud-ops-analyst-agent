"""Shared hashing helpers for audit correlation."""

from __future__ import annotations

import json
from hashlib import sha256
from typing import Any


def hash_llm_reasoning(reasoning: dict[str, Any] | None) -> str | None:
    """Create a stable hash for an LLM reasoning payload."""
    if not isinstance(reasoning, dict):
        return None

    narrative = str(reasoning.get("narrative", "")).strip()
    if not narrative:
        return None

    basis = {
        "model_mode": reasoning.get("model_mode"),
        "narrative": narrative,
        "risk_assessment": reasoning.get("risk_assessment"),
        "confidence": reasoning.get("confidence"),
    }
    return sha256(json.dumps(basis, sort_keys=True).encode("utf-8")).hexdigest()


def hash_summary_text(summary: str | None) -> str | None:
    """Create a stable hash for persisted insight summary text."""
    text = str(summary or "").strip()
    if not text:
        return None
    return sha256(json.dumps({"summary": text}, sort_keys=True).encode("utf-8")).hexdigest()
