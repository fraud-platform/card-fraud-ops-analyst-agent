# TDD-006: Testing & Quality Strategy

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** TDD-001 through TDD-005

---

## 1. Overview

All existing tests are invalidated by the architecture change. Pure core logic tests are preserved (moved to `tests/unit/tools/_core/`). New test categories: tool tests, planner tests, graph integration tests, replay tests. Same quality gates (ruff lint, ruff format, pytest unit + smoke). Testing strategy emphasizes deterministic behavior, tool isolation, and planner correctness.

---

## 2. Test Directory Structure

```
tests/
├── conftest.py                          # Updated: LangGraph fixtures, mock registry
├── unit/
│   ├── tools/
│   │   ├── _core/
│   │   │   ├── test_pattern_logic.py    # PRESERVED from test_pattern_engine_core.py
│   │   │   ├── test_similarity_logic.py # PRESERVED from test_similarity_engine_core.py
│   │   │   ├── test_recommendation_logic.py  # PRESERVED
│   │   │   ├── test_context_logic.py    # PRESERVED from test_context_builder_core.py
│   │   │   └── test_reasoning_logic.py  # PRESERVED
│   │   ├── test_context_tool.py         # NEW: mock TM client
│   │   ├── test_pattern_tool.py         # NEW: mock state
│   │   ├── test_similarity_tool.py      # NEW: mock embedding + DB
│   │   ├── test_reasoning_tool.py       # NEW: mock LangChain ChatModel
│   │   ├── test_recommendation_tool.py  # NEW
│   │   └── test_rule_draft_tool.py      # NEW
│   ├── agent/
│   │   ├── test_planner.py              # NEW: mock LLM, test tool selection
│   │   ├── test_executor.py             # NEW: mock tool, test execution
│   │   ├── test_completion.py           # NEW: mock persistence
│   │   ├── test_registry.py             # NEW: register/get/list
│   │   ├── test_state.py               # NEW: state factory, serialization
│   │   └── test_graph.py               # NEW: graph topology validation
│   ├── persistence/
│   │   ├── test_state_store.py          # NEW: mock session
│   │   ├── test_investigation_repo.py   # NEW: replaces test_run_repository
│   │   ├── test_tool_log_repo.py        # NEW
│   │   ├── test_insight_repository.py   # PRESERVED
│   │   ├── test_recommendation_repository.py  # PRESERVED
│   │   └── test_audit_repository.py     # PRESERVED
│   ├── clients/
│   │   ├── test_tm_client.py            # NEW: mock HTTP
│   │   └── test_embedding_client.py     # PRESERVED
│   ├── core/
│   │   ├── test_config.py               # UPDATED: new config classes
│   │   ├── test_auth.py                 # PRESERVED
│   │   └── test_errors.py              # PRESERVED
│   ├── schemas/
│   │   └── test_investigation_schemas.py  # NEW
│   └── llm/
│       └── test_provider.py             # NEW: LangChain factory tests
├── smoke/
│   └── test_api_smoke.py               # UPDATED: new endpoint shapes
├── integration/
│   ├── test_graph_integration.py        # NEW: full graph with mock LLM
│   └── test_database_integration.py     # UPDATED: new table names
└── e2e/
    └── test_investigation_flow.py       # NEW: end-to-end with real LLM
```

---

## 3. Test Fixtures (Root conftest.py)

```python
import pytest
from unittest.mock import AsyncMock, MagicMock
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage

from app.agent.state import create_initial_state, InvestigationState
from app.agent.registry import ToolRegistry
from app.tools.base import BaseTool


# ── Environment Setup ─────────────────────────────────────────

@pytest.fixture(autouse=True)
def _set_test_env(monkeypatch):
    """Force test environment."""
    monkeypatch.setenv("APP_ENV", "local")
    monkeypatch.setenv("SECURITY_SKIP_JWT_VALIDATION", "true")


# ── LangChain Mock ────────────────────────────────────────────

@pytest.fixture
def mock_chat_model():
    """Mock LangChain ChatModel that returns a valid planner decision."""
    model = AsyncMock(spec=BaseChatModel)
    model.ainvoke.return_value = AIMessage(
        content='{"tool": "pattern_tool", "reason": "Analyze fraud patterns", "confidence": 0.9}'
    )
    return model


@pytest.fixture
def mock_chat_model_complete():
    """Mock ChatModel that always decides to COMPLETE."""
    model = AsyncMock(spec=BaseChatModel)
    model.ainvoke.return_value = AIMessage(
        content='{"tool": "COMPLETE", "reason": "Investigation sufficient", "confidence": 0.95}'
    )
    return model


# ── Tool Registry ─────────────────────────────────────────────

@pytest.fixture
def mock_tool_factory():
    """Factory to create mock tools that echo their name into state."""
    def _create(name: str, description: str = "") -> BaseTool:
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
    """Registry with 6 mock tools."""
    registry = ToolRegistry()
    for name in [
        "context_tool", "pattern_tool", "similarity_tool",
        "reasoning_tool", "recommendation_tool", "rule_draft_tool",
    ]:
        registry.register(mock_tool_factory(name))
    return registry


# ── Investigation State ───────────────────────────────────────

@pytest.fixture
def initial_state():
    """Fresh investigation state."""
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
            "window_1h": {"transaction_count": 1, "total_amount": 500.0},
            "window_24h": {"transaction_count": 3, "total_amount": 1200.0},
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


# ── Database Mock ─────────────────────────────────────────────

@pytest.fixture
def mock_session():
    """Mock AsyncSession for repository tests."""
    session = AsyncMock()
    session.execute = AsyncMock()
    session.commit = AsyncMock()
    session.rollback = AsyncMock()
    return session


# ── TM Client Mock ────────────────────────────────────────────

@pytest.fixture
def mock_tm_client():
    """Mock TM API client (matches TDD-007 corrected interface)."""
    client = AsyncMock()
    client.get_transaction_overview.return_value = {
        "transaction": {
            "transaction_id": "txn-test-123",
            "amount": 500.00,
            "currency": "USD",
            "merchant_id": "merch-001",
            "card_id": "card-001",
            "timestamp": "2026-02-19T10:00:00Z",
            "location": {"country": "US", "city": "New York"},
        },
        "review": None,
        "notes": [],
        "case": None,
        "matched_rules": [],
    }
    client.get_card_history.return_value = []
    client.get_merchant_history.return_value = []
    client.health_check.return_value = True
    return client
```

---

## 4. Key Test Scenarios

### 4.1 Planner Tests (`tests/unit/agent/test_planner.py`)

| Test | Description |
|------|-------------|
| `test_selects_context_first_when_empty` | Planner selects `context_tool` when `context` is empty |
| `test_selects_analysis_after_context` | Planner selects `pattern_tool` or `similarity_tool` after context is populated |
| `test_selects_reasoning_after_analysis` | Planner selects `reasoning_tool` only after analysis tools complete |
| `test_selects_complete_when_done` | Planner returns `COMPLETE` when all steps are done |
| `test_never_repeats_completed_tool` | Planner never selects a tool already in `completed_steps` |
| `test_respects_ordering_constraints` | Cannot select `recommendation_tool` before analysis |
| `test_fallback_on_llm_failure` | Falls back to deterministic sequence when LLM times out |
| `test_fallback_on_invalid_response` | Falls back when LLM returns invalid JSON or unknown tool name |
| `test_decision_logged` | `PlannerDecision` appended to `planner_decisions` list |
| `test_confidence_recorded` | Confidence score from LLM response stored in decision |

### 4.2 Tool Executor Tests (`tests/unit/agent/test_executor.py`)

| Test | Description |
|------|-------------|
| `test_executes_named_tool` | Executor calls `tool.execute(state)` for `state["next_action"]` |
| `test_records_execution_time` | `ToolExecution.execution_time_ms` is populated |
| `test_appends_to_completed_steps` | Tool name added to `completed_steps` |
| `test_handles_tool_timeout` | `asyncio.TimeoutError` → status `TIMED_OUT`, tool still marked completed |
| `test_handles_tool_exception` | Generic exception → status `FAILED`, error captured, planner continues |
| `test_increments_step_count` | `step_count` incremented after execution |

### 4.3 Graph Tests (`tests/unit/agent/test_graph.py`)

| Test | Description |
|------|-------------|
| `test_graph_compiles` | `build_investigation_graph()` returns a compiled graph |
| `test_graph_has_three_nodes` | planner, tool_executor, completion nodes exist |
| `test_graph_routes_to_tool_executor` | When `next_action` is a tool name, routes to `tool_executor` |
| `test_graph_routes_to_completion` | When `next_action` is `COMPLETE`, routes to `completion` |
| `test_graph_routes_on_max_steps` | When `step_count >= max_steps`, routes to `completion` |
| `test_full_investigation_flow` | Mock all tools + LLM, run full graph, verify final state |

### 4.4 Tool Tests (per tool)

Each tool test file follows the same pattern:

| Test | Description |
|------|-------------|
| `test_populates_expected_state_fields` | Tool sets its target state fields |
| `test_preserves_existing_state` | Non-target fields unchanged |
| `test_idempotent` | Running twice produces same result |
| `test_handles_missing_prerequisites` | Raises or returns gracefully when input missing |

#### Context Tool Specifics

| Test | Description |
|------|-------------|
| `test_calls_tm_api` | Verifies TM client methods called with correct args |
| `test_enriches_context` | `state["context"]` has transaction, card_history, merchant, windows |
| `test_handles_tm_api_failure` | Raises on TM API error (executor catches) |

#### Reasoning Tool Specifics

| Test | Description |
|------|-------------|
| `test_calls_llm` | Verifies LangChain ChatModel called with correct messages |
| `test_redacts_pii` | PII removed from LLM input |
| `test_deterministic_fallback` | Falls back gracefully when LLM fails |
| `test_updates_severity_and_confidence` | State fields updated from reasoning output |

### 4.5 Registry Tests (`tests/unit/agent/test_registry.py`)

| Test | Description |
|------|-------------|
| `test_register_and_get` | Register tool, retrieve by name |
| `test_get_unknown_raises` | `KeyError` for unregistered tool |
| `test_list_tools` | Returns name + description for all registered tools |
| `test_duplicate_registration_raises` | Cannot register same name twice |
| `test_has` | `has()` returns True for registered, False otherwise |

### 4.6 State Tests (`tests/unit/agent/test_state.py`)

| Test | Description |
|------|-------------|
| `test_create_initial_state` | Factory creates valid state with all defaults |
| `test_state_json_serializable` | `json.dumps(state)` succeeds |
| `test_state_fields_exist` | All required TypedDict fields present |
| `test_custom_max_steps` | `max_steps` parameter respected |

---

## 5. Preserved Tests (Move, Don't Rewrite)

These tests are preserved with minimal changes (import path updates only):

| Current Path | New Path | Changes |
|-------------|----------|---------|
| `tests/unit/test_context_builder_core.py` | `tests/unit/tools/_core/test_context_logic.py` | Update imports: `app.agents.context_builder_core` → `app.tools._core.context_logic` |
| `tests/unit/test_pattern_engine_core.py` | `tests/unit/tools/_core/test_pattern_logic.py` | Update imports: `app.agents.pattern_engine_core` → `app.tools._core.pattern_logic` |
| `tests/unit/test_similarity_engine_core.py` | `tests/unit/tools/_core/test_similarity_logic.py` | Update imports: `app.agents.similarity_engine_core` → `app.tools._core.similarity_logic` |
| `tests/unit/test_recommendation_engine_core.py` | `tests/unit/tools/_core/test_recommendation_logic.py` | Update imports: `app.agents.recommendation_engine_core` → `app.tools._core.recommendation_logic` |
| `tests/unit/test_auth.py` | `tests/unit/core/test_auth.py` | No changes |
| `tests/unit/test_errors.py` | `tests/unit/core/test_errors.py` | No changes |
| `tests/unit/test_config.py` | `tests/unit/core/test_config.py` | Add tests for `LangGraphConfig`, `PlannerConfig`, `TMClientConfig` |
| `tests/unit/test_insight_repository.py` | `tests/unit/persistence/test_insight_repository.py` | No changes |
| `tests/unit/test_recommendation_repository.py` | `tests/unit/persistence/test_recommendation_repository.py` | No changes |
| `tests/unit/test_audit_repository.py` | `tests/unit/persistence/test_audit_repository.py` | No changes |
| `tests/unit/test_embedding_client.py` | `tests/unit/clients/test_embedding_client.py` | No changes |

---

## 6. Tests to Delete (No Longer Applicable)

| Current Path | Reason |
|-------------|--------|
| `tests/unit/test_pipeline.py` | Pipeline deleted, replaced by graph tests |
| `tests/unit/test_pipeline_*.py` | All pipeline-related tests |
| `tests/unit/test_context_builder.py` | DB-bound adapter deleted |
| `tests/unit/test_pattern_engine.py` | DB-bound adapter deleted |
| `tests/unit/test_similarity_engine.py` | DB-bound adapter deleted |
| `tests/unit/test_recommendation_engine.py` | DB-bound adapter deleted |
| `tests/unit/test_reasoning_engine.py` | Replaced by reasoning_tool tests |
| `tests/unit/test_rule_draft_engine.py` | Replaced by rule_draft_tool tests |
| `tests/unit/test_action_planner.py` | Replaced by planner tests |
| `tests/unit/test_conflict_matrix.py` | Absorbed or removed |
| `tests/unit/test_evidence_builder.py` | Absorbed into tools |
| `tests/unit/test_explanation_builder.py` | Absorbed into completion |
| `tests/unit/test_investigation_service.py` | Rewritten for new service |
| `tests/unit/test_insight_service.py` | Service deleted |
| `tests/unit/test_rule_draft_service.py` | Service deleted |
| `tests/unit/test_run_repository.py` | Replaced by investigation_repo tests |
| `tests/unit/test_context_reader.py` | Replaced by TM client tests |
| `tests/unit/test_llm_provider.py` | Replaced by LangChain provider tests |
| `tests/smoke/test_api_smoke.py` | Rewritten for new API shape |
| `tests/e2e/*` | Rewritten for graph-based flow |

---

## 7. Smoke Tests (`tests/smoke/test_api_smoke.py`)

```python
"""Smoke tests for API endpoint shapes and auth."""

from fastapi.testclient import TestClient
from app.main import create_app


def test_health_endpoint():
    client = TestClient(create_app())
    response = client.get("/api/v1/health")
    assert response.status_code == 200


def test_run_investigation_requires_auth():
    client = TestClient(create_app())
    response = client.post("/api/v1/ops-agent/investigations/run", json={
        "transaction_id": "txn-123"
    })
    # Should succeed with skip_jwt_validation=true in test env
    # or return 401 if auth is enforced
    assert response.status_code in (200, 401, 422)


def test_get_investigation_404():
    client = TestClient(create_app())
    response = client.get("/api/v1/ops-agent/investigations/nonexistent-id")
    assert response.status_code in (404, 401)


def test_recommendations_worklist():
    client = TestClient(create_app())
    response = client.get("/api/v1/ops-agent/worklist/recommendations")
    assert response.status_code in (200, 401)


def test_resume_investigation_404():
    client = TestClient(create_app())
    response = client.post("/api/v1/ops-agent/investigations/nonexistent/resume")
    assert response.status_code in (404, 401)
```

---

## 8. Integration Tests (`tests/integration/test_graph_integration.py`)

Full graph execution with mock LLM but real tool logic:

```python
"""Integration test: full investigation graph with deterministic planner."""

import pytest
from app.agent.graph import build_investigation_graph
from app.agent.state import create_initial_state
from app.agent.registry import ToolRegistry


@pytest.mark.integration
async def test_full_investigation_deterministic():
    """Run full investigation with deterministic planner fallback."""
    # Setup: mock LLM to always fail → triggers deterministic fallback
    # Setup: mock TM client with canned responses
    # Setup: mock embedding client

    graph = build_investigation_graph(registry, mock_llm, settings)
    state = create_initial_state("inv-int-001", "txn-int-123")

    result = await graph.ainvoke(state)

    assert result["status"] == "COMPLETED"
    assert len(result["completed_steps"]) >= 4  # At least context + patterns + reasoning + reco
    assert result["recommendations"]  # Should have recommendations
    assert result["step_count"] <= 20  # Within limits


@pytest.mark.integration
async def test_max_steps_enforced():
    """Verify investigation terminates at max_steps."""
    state = create_initial_state("inv-int-002", "txn-int-456", max_steps=3)
    result = await graph.ainvoke(state)

    assert result["step_count"] <= 3
    assert result["status"] == "COMPLETED"


@pytest.mark.integration
async def test_resume_from_persisted_state():
    """Verify investigation can resume from any saved state."""
    # 1. Run investigation partially (mock tool to raise after step 2)
    # 2. Save state to state_store
    # 3. Load state
    # 4. Resume via graph.ainvoke(loaded_state)
    # 5. Verify completion
```

---

## 9. Quality Gates (Unchanged)

```bash
# Gate 1: Lint (Zero Errors)
uv run ruff check app/ tests/ cli/ scripts/

# Gate 2: Format (Clean)
uv run ruff format --check app/ tests/ cli/ scripts/

# Gate 3: Unit Tests (All Pass)
uv run pytest tests/unit -v

# Gate 4: Smoke Tests (All Pass)
uv run pytest tests/smoke -v

# Gate 5: Integration Tests (When DB Available)
doppler run --config local-test -- uv run pytest tests/integration -v

# Combined (Gates 1-4):
uv run ruff check app/ tests/ cli/ scripts/ && uv run ruff format --check app/ tests/ cli/ scripts/ && uv run pytest tests/unit tests/smoke -v
```

---

## 10. Coverage Targets

| Module | Target | Notes |
|--------|--------|-------|
| `app/agent/` | ≥90% | Core agent runtime — planner, executor, completion, graph |
| `app/tools/` | ≥90% | All tools including error paths |
| `app/tools/_core/` | ≥95% | Pure logic — preserved from existing high-coverage tests |
| `app/persistence/` | ≥85% | Repository SQL validation |
| `app/clients/` | ≥80% | HTTP client mocking |
| `app/services/` | ≥85% | Service orchestration |
| `app/api/routes/` | ≥80% | Route handler validation |
| **Overall** | **≥85%** | |

Generate coverage report:

```bash
uv run pytest tests/ --cov=app --cov-report=html:htmlcov --cov-branch \
    --html=htmlcov/test-report.html --self-contained-html
```

---

## 11. Test Execution Order for Development

When implementing the rewrite, run tests in this order to validate each phase:

| Phase | Test Command | What It Validates |
|-------|-------------|-------------------|
| Phase 1 (State) | `pytest tests/unit/agent/test_state.py -v` | State model + factory |
| Phase 2 (Registry) | `pytest tests/unit/agent/test_registry.py -v` | Tool registration |
| Phase 3 (Tools) | `pytest tests/unit/tools/ -v` | All tool logic |
| Phase 4 (TM Client) | `pytest tests/unit/clients/test_tm_client.py -v` | TM API client |
| Phase 5 (LLM) | `pytest tests/unit/llm/ -v` | LangChain provider |
| Phase 6 (Planner) | `pytest tests/unit/agent/test_planner.py -v` | Planner decisions |
| Phase 7 (Graph) | `pytest tests/unit/agent/test_graph.py -v` | Graph topology + execution |
| Phase 8 (Persistence) | `pytest tests/unit/persistence/ -v` | State store + repos |
| Phase 9 (API) | `pytest tests/smoke/ -v` | API endpoints |
| Phase 10 (Observability) | `pytest tests/unit/ -v` | Full unit suite |
| Phase 11 (Full) | Quality gates command | All gates pass |

---

## 12. AGENTS.md Update Checklist

After implementation, `AGENTS.md` must be updated to reflect:

- [ ] New project structure (`app/agent/`, `app/tools/`, etc.)
- [ ] New quality gate expectations (same commands, new test file paths)
- [ ] LangGraph architecture description
- [ ] Tool-based investigation model
- [ ] TM API dependency and `TM_BASE_URL` secret
- [ ] LangChain LLM provider (replace LiteLLM references)
- [ ] New database tables (`ops_agent_investigation_state`, `ops_agent_tool_execution_log`)
- [ ] Renamed table (`ops_agent_investigations` from `ops_agent_runs`)
- [ ] New Doppler secrets (`TM_BASE_URL`, `LANGGRAPH_*`, `PLANNER_*`)
- [ ] Updated `pyproject.toml` dependencies
- [ ] Removal of all pipeline/linear references
- [ ] Updated learnings section
