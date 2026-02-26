"""Unit tests for evidence helper utilities."""

from __future__ import annotations

from app.agent.state import create_initial_state
from app.tools.evidence import EvidenceEntry, append_evidence


def test_evidence_entry_to_dict() -> None:
    entry = EvidenceEntry(
        category="pattern_analysis",
        tool="pattern_tool",
        description="Detected 2 fraud patterns",
        data={"overall_score": 0.84},
    )

    assert entry.to_dict() == {
        "category": "pattern_analysis",
        "tool": "pattern_tool",
        "description": "Detected 2 fraud patterns",
        "data": {"overall_score": 0.84},
    }


def test_append_evidence_appends_and_updates_state() -> None:
    state = create_initial_state("inv-1", "txn-1")
    entry = EvidenceEntry(
        category="similarity_analysis",
        tool="similarity_tool",
        description="Found 3 similar transactions",
        data={"match_count": 3},
    )

    updated = append_evidence(state, entry, severity="MEDIUM")

    assert len(updated["evidence"]) == 1
    assert updated["evidence"][0]["tool"] == "similarity_tool"
    assert updated["severity"] == "MEDIUM"
