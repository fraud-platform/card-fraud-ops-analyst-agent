"""Unit tests for completion severity calibration."""

from __future__ import annotations

import pytest

from app.agent.completion import _determine_severity, completion_node
from app.agent.state import create_initial_state


def test_determine_severity_keeps_current_level_when_valid() -> None:
    assert _determine_severity(0.95, "LOW") == "LOW"
    assert _determine_severity(0.15, "HIGH") == "HIGH"


def test_determine_severity_falls_back_to_confidence_when_invalid() -> None:
    assert _determine_severity(0.75, "UNKNOWN") == "HIGH"
    assert _determine_severity(0.1, "") == "LOW"


@pytest.mark.asyncio
async def test_completion_node_does_not_escalate_low_risk_by_confidence() -> None:
    state = create_initial_state("inv-1", "txn-1")
    state.update(
        {
            "status": "IN_PROGRESS",
            "severity": "LOW",
            "reasoning": {"confidence": 0.95, "risk_level": "LOW"},
            "pattern_results": {"overall_confidence": 0.0},
            "similarity_results": {"overall_score": 0.0},
            "step_count": 6,
        }
    )

    completed = await completion_node(state)
    assert completed["confidence_score"] == 0.95
    assert completed["severity"] == "LOW"
