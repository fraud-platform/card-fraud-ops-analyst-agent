"""Unit tests for investigation state model."""

import json

from app.agent.state import create_initial_state


class TestInvestigationState:
    """Tests for InvestigationState TypedDict."""

    def test_create_initial_state(self):
        """Factory creates valid state with all defaults."""
        state = create_initial_state("inv-001", "txn-001")

        assert state["investigation_id"] == "inv-001"
        assert state["transaction_id"] == "txn-001"
        assert state["status"] == "PENDING"
        assert state["step_count"] == 0
        assert state["max_steps"] == 20
        assert state["context"] == {}
        assert state["pattern_results"] == {}
        assert state["similarity_results"] == {}
        assert state["completed_steps"] == []
        assert state["planner_decisions"] == []
        assert state["tool_executions"] == []
        assert state["error"] is None

    def test_create_initial_state_custom_max_steps(self):
        """Factory respects custom max_steps."""
        state = create_initial_state("inv-001", "txn-001", max_steps=10)
        assert state["max_steps"] == 10

    def test_state_json_serializable(self):
        """State is fully JSON-serializable."""
        state = create_initial_state("inv-001", "txn-001")

        # Should not raise
        json_str = json.dumps(state)

        # Should be able to parse back
        parsed = json.loads(json_str)
        assert parsed["investigation_id"] == "inv-001"

    def test_state_fields_exist(self):
        """All required TypedDict fields present."""
        state = create_initial_state("inv-001", "txn-001")

        required_fields = [
            "investigation_id",
            "transaction_id",
            "context",
            "pattern_results",
            "similarity_results",
            "hypotheses",
            "evidence",
            "reasoning",
            "recommendations",
            "rule_draft",
            "confidence_score",
            "severity",
            "status",
            "completed_steps",
            "next_action",
            "step_count",
            "max_steps",
            "started_at",
            "completed_at",
            "planner_decisions",
            "tool_executions",
            "error",
            "feature_flags",
            "safeguards",
        ]

        for field in required_fields:
            assert field in state, f"Missing field: {field}"
