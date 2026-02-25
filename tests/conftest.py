"""Root conftest for tests."""

import os
from unittest.mock import AsyncMock

import pytest

if os.getenv("APP_ENV", "").strip().lower() == "prod":
    raise RuntimeError("Refusing to run tests with APP_ENV=prod")

os.environ["APP_ENV"] = "local"
os.environ["SECURITY_SKIP_JWT_VALIDATION"] = "true"
os.environ.setdefault("SERVER_PORT", "8003")
os.environ.setdefault("METRICS_TOKEN", "test-metrics-token")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply markers based on test directory structure."""
    dir_marker_map = {
        "unit": pytest.mark.unit,
        "smoke": pytest.mark.smoke,
        "integration": pytest.mark.integration,
        "e2e": pytest.mark.e2e,
    }
    for item in items:
        test_path = str(item.fspath)
        for dir_name, marker in dir_marker_map.items():
            if f"/{dir_name}/" in test_path or f"\\{dir_name}\\" in test_path:
                item.add_marker(marker)
                break


@pytest.fixture
def mock_session():
    """Mock database session for tests."""

    class MockSession:
        async def execute(self, *args, **kwargs):
            class MockResult:
                def fetchone(self):
                    return None

                def fetchall(self):
                    return []

            return MockResult()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    return MockSession()


# ── LangGraph Agent Fixtures ─────────────────────────────────────


@pytest.fixture
def initial_state():
    """Fresh investigation state for tests."""
    from app.agent.state import create_initial_state

    return create_initial_state("inv-test-001", "txn-test-123")


@pytest.fixture
def state_with_context(initial_state):
    """State after context_tool has run."""
    return {
        **initial_state,
        "context": {
            "transaction": {
                "transaction_id": "txn-test-123",
                "amount": 500.00,
                "currency": "USD",
                "merchant_id": "merch-001",
                "card_id": "card-001",
                "user_id": "user-001",
            },
            "card_history": [],
            "merchant_profile": {},
        },
        "completed_steps": ["context_tool"],
        "step_count": 1,
    }


@pytest.fixture
def state_with_analysis(state_with_context):
    """State after pattern + similarity tools have run."""
    return {
        **state_with_context,
        "pattern_results": {
            "scores": [{"pattern_name": "velocity", "score": 0.8, "weight": 1.0}],
            "overall_score": 0.8,
            "patterns_detected": ["velocity"],
        },
        "similarity_results": {
            "matches": [],
            "overall_score": 0.0,
        },
        "evidence": [
            {"category": "pattern_analysis", "tool": "pattern_tool"},
            {"category": "similarity_analysis", "tool": "similarity_tool"},
        ],
        "completed_steps": ["context_tool", "pattern_tool", "similarity_tool"],
        "step_count": 3,
    }


@pytest.fixture
def mock_chat_model():
    """Mock LangChain ChatModel for tests."""
    from langchain_core.messages import AIMessage

    model = AsyncMock()
    model.ainvoke.return_value = AIMessage(
        content='{"tool": "pattern_tool", "reason": "Analyze patterns", "confidence": 0.9}'
    )
    return model


@pytest.fixture
def mock_tool_factory():
    """Factory to create mock tools."""

    def _create(name: str, description: str = ""):
        from app.tools.base import BaseTool

        tool = AsyncMock(spec=BaseTool)
        tool.name = name
        tool.description = description or f"Mock {name}"

        async def mock_execute(state):
            return {
                **state,
                "completed_steps": [*state["completed_steps"], name],
            }

        tool.execute = AsyncMock(side_effect=mock_execute)
        return tool

    return _create


@pytest.fixture
def mock_registry(mock_tool_factory):
    """Registry with mock tools."""
    from app.agent.registry import ToolRegistry

    registry = ToolRegistry()
    for name in [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "reasoning_tool",
        "recommendation_tool",
        "rule_draft_tool",
    ]:
        registry.register(mock_tool_factory(name))
    return registry


@pytest.fixture
def mock_tm_client():
    """Mock TM API client for tests (TDD-007 interface)."""
    client = AsyncMock()
    client.get_transaction_overview.return_value = {
        "transaction": {
            "transaction_id": "txn-test-123",
            "amount": 500.00,
            "currency": "USD",
            "merchant_id": "merch-001",
            "card_id": "card-001",
            "timestamp": "2026-02-19T10:00:00Z",
        },
        "review": None,
        "notes": [],
        "case": None,
        "matched_rules": [],
        "last_activity_at": None,
    }
    client.get_card_history.return_value = []
    client.get_merchant_history.return_value = []
    client.health_check.return_value = True
    client.close.return_value = None
    return client
