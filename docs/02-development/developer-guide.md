# Developer Guide (Agentic Runtime)

This guide is the canonical developer workflow for the current LangGraph-based agentic implementation.

## Prerequisites

- Python 3.14
- [uv](https://docs.astral.sh/uv/)
- [Doppler CLI](https://docs.doppler.com/docs/install-cli)
- Docker Desktop

## Quick Start

```bash
# Install dependencies
uv sync --extra dev

# Configure Doppler once
doppler setup --project card-fraud-ops-analyst-agent --config local

# Create/upgrade ops_agent_* tables
uv run db-init

# Start service on port 8003
uv run doppler-local
```

- API base: `http://localhost:8003`
- OpenAPI docs: `http://localhost:8003/docs`

## Core Commands

```bash
# Lint + format
uv run ruff check app/ tests/ cli/ scripts/
uv run ruff format --check app/ tests/ cli/ scripts/

# Tests
uv run pytest tests/unit -v
uv run pytest tests/smoke -v
uv run doppler-local-test

# E2E prerequisite (from card-fraud-platform directory)
doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d --build transaction-management ops-analyst-agent

# E2E scenario run (seed + suites)
doppler run --config local -- uv run python scripts/seed_test_scenarios.py
uv run pytest tests/e2e/test_scenarios.py -v
uv run python scripts/run_e2e_matrix_detailed.py
```

## Runtime Shape

Execution is graph-driven:

1. `planner_node` selects the next action.
2. `executor_node` runs one tool.
3. Tool output updates graph state.
4. Loop continues until `completion_node` ends investigation.

Primary modules:

- `app/agent/` - planner, executor, completion, graph wiring, shared state
- `app/tools/` - context, pattern, similarity, reasoning, recommendation, rule draft
- `app/persistence/` - investigation, tool log, insight, recommendation, rule draft repositories
- `app/services/investigation_service.py` - API-facing orchestration and response assembly

## Configuration Notes

- `OPS_AGENT_ENABLE_LLM_REASONING=true` keeps reasoning stage active.
- `VECTOR_ENABLED=true` enables embedding + similarity retrieval.
- `LLM_PROVIDER`, `LLM_BASE_URL`, and `OLLAMA_API_KEY` must be set in Doppler.
- Planner and reasoning are LLM-backed with guarded fallback behavior for error resilience.

## Quality Gate Policy

Before merge, all must pass:

```bash
uv run ruff check app/ tests/ cli/ scripts/
uv run ruff format --check app/ tests/ cli/ scripts/
uv run pytest tests/unit tests/smoke -v
```

Use hooks:

```bash
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files
```
