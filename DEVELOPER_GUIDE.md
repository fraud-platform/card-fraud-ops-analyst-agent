# Developer Guide

## Prerequisites

- Python 3.14 (required for `uuid.uuid7` stdlib support)
- [uv](https://docs.astral.sh/uv/) — the only allowed package manager (never pip)
- [Doppler CLI](https://docs.doppler.com/docs/install-cli) — the only allowed secrets manager (never .env files)
- Docker Desktop — for running PostgreSQL locally via `card-fraud-platform`
- Auth0 access — tenant `dev-gix6qllz7yvs0rl8.us.auth0.com`

## Quick Start

```bash
# 1. Clone and install
git clone <repo-url>
cd card-fraud-ops-analyst-agent
uv sync --extra dev

# 2. Configure Doppler (run once per machine)
doppler setup --project card-fraud-ops-analyst-agent --config local

# 3. Start platform infrastructure (from sibling repo)
cd ../card-fraud-platform
docker compose up -d
cd ../card-fraud-ops-analyst-agent

# 4. Initialize this project's database tables
uv run db-init

# 5. Start the dev server
uv run doppler-local
# Server available at http://localhost:8003
# OpenAPI docs at http://localhost:8003/docs
```

## Quality Gates

All four gates must pass before merging. There are no exceptions.

```bash
uv run ruff check app/ tests/ cli/ scripts/           # Lint — 0 errors required
uv run ruff format --check app/ tests/ cli/ scripts/  # Format — clean required
uv run pytest tests/unit -v                            # Unit tests — 140 tests
uv run pytest tests/smoke -v                           # Smoke tests — 10 tests
```

Run all tests together:

```bash
uv run doppler-local-test   # Runs full test suite with local DB secrets from Doppler
```

## CLI Commands Reference

All commands are invoked via `uv run <command>`.

### Development

| Command | Description |
|---------|-------------|
| `doppler-local` | Start dev server on port 8003 with Doppler secrets (local config) |
| `doppler-local-test` | Run test suite with local DB secrets from Doppler |
| `doppler-test` | Run test suite with test environment secrets |
| `dev` | Start server without Doppler (requires env vars set manually) |

### Auth0

| Command | Description |
|---------|-------------|
| `auth0-bootstrap --yes --verbose` | One-time: create Auth0 API + M2M client, sync to Doppler |
| `auth0-verify` | Verify Auth0 configuration is correct |

### Database (ops_agent_* tables only)

| Command | Description |
|---------|-------------|
| `db-init` | Run migrations to create `ops_agent_*` tables in local DB |
| `db-init-test` | Run migrations in test DB |
| `db-reset-tables` | Drop and recreate `ops_agent_*` tables (local) |
| `db-reset-tables-test` | Drop and recreate `ops_agent_*` tables (test) |
| `db-reset-data` | Reset seed data in local DB |
| `db-reset-data-test` | Reset seed data in test DB |
| `db-verify` | Verify `ops_agent_*` tables exist in local DB |
| `db-verify-test` | Verify tables in test DB |
| `db-verify-prod` | Verify tables in prod DB |
| `db-load-test-data` | Load test data from real DECLINE transactions (idempotent) |
| `db-load-test-data-test` | Load test data into test DB |

### Testing

| Command | Description |
|---------|-------------|
| `test` | Run unit tests |
| `test-smoke` | Run smoke tests |
| `test-all` | Run all tests (unit + smoke) |
| `e2e-local` | Run end-to-end tests (requires running server + DB) |

### Code Quality

| Command | Description |
|---------|-------------|
| `lint` | Run `ruff check` |
| `format` | Run `ruff format` |
| `generate-openapi` | Generate OpenAPI schema to file |

## Architecture

### Core/Adapter Split

Every agent pipeline stage is split into two files:

- `*_core.py` — pure Python logic, no DB calls, fully unit-testable with no mocking required
- `*.py` — DB-bound adapter that calls the core function and persists results

Example:
```
app/agents/pattern_engine_core.py    # Pure scoring logic
app/agents/pattern_engine.py         # Fetches evidence from DB, calls core, persists results
```

This split keeps business logic fast to test and easy to reason about.

### Request Flow

```
FastAPI route
  -> Service (investigation_service, insight_service, etc.)
    -> Pipeline (pipeline.py orchestrates agent stages)
      -> Agent adapters (context_builder, pattern_engine, recommendation_engine, ...)
        -> *_core.py (pure logic)
        -> Persistence repositories (run_repository, insight_repository, ...)
          -> asyncpg via SQLAlchemy Core
```

### Database Isolation

- This service reads from `fraud_gov` schema (shared with Transaction Management, Rule Management).
- This service writes only to `ops_agent_*` tables.
- Never drop or alter `fraud_gov` schema objects. Never use `DATABASE_URL_APP` for DDL.
- DB scripts use `DATABASE_URL_ADMIN` for table creation/migration.

### Auth Pattern

Scopes are enforced via typed dependency aliases:

```python
# In route handlers:
analyst: Annotated[AuthenticatedUser, Depends(require_scope("ops_agent:read"))]
```

Auth0 scopes: `ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `ops_agent:draft`, `ops_agent:admin`.

## LLM Configuration

LLM reasoning is **off by default**. When disabled, the pipeline runs in deterministic-only mode — no LLM calls are made and no API key is required.

To enable, set these secrets in Doppler (`local` config) using one of the two options below.

### Option A: Ollama (Local LLM — free, no API key needed)

**1. Install and start Ollama**

```bash
# Download from https://ollama.com/download
# Then pull the model:
ollama pull llama3.2

# Verify it works:
ollama run llama3.2 "hello"
```

**2. Set Doppler secrets**

```bash
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING="true" --config local
doppler secrets set LLM_PROVIDER="ollama_chat/llama3.2" --config local
doppler secrets set LLM_BASE_URL="http://localhost:11434" --config local
doppler secrets set LLM_API_KEY="ollama" --config local
doppler secrets set LLM_TIMEOUT="120" --config local
```

> **Note:** Small models (3B parameters) may not reliably produce valid JSON.
> The pipeline automatically falls back to deterministic mode if LLM output is invalid.
> For better results use `llama3.1:8b` or larger.

---

### Option B: Anthropic-compatible Cloud API (ZAI / Claude)

Any provider that implements the Anthropic API spec works (e.g. ZAI GLM, direct Anthropic).

**1. Get your API key** from your provider's dashboard.

**2. Set Doppler secrets**

```bash
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING="true" --config local
doppler secrets set LLM_PROVIDER="anthropic/claude-haiku-4-5-20251001" --config local
doppler secrets set LLM_BASE_URL="https://<your-provider-base-url>/api/anthropic" --config local
doppler secrets set LLM_API_KEY="<your-api-key>" --config local
doppler secrets set LLM_TIMEOUT="60" --config local
```

Replace `<your-provider-base-url>` and `<your-api-key>` with your actual values.
For direct Anthropic API, set `LLM_BASE_URL=""` (empty — LiteLLM uses the default).

---

### Verify LLM is active

After restarting the server (`uv run doppler-local`), run the E2E test and check for `"model_mode": "hybrid"` in the response:

```bash
uv run e2e-local
```

If you see `"model_mode": "deterministic"`, the LLM reasoning fell back (check server logs for the reason).

### Revert to deterministic mode

```bash
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING="false" --config local
```

When `OPS_AGENT_ENABLE_LLM_REASONING=false`, the pipeline runs in deterministic-only mode and no LLM calls are made.

## Testing

### Unit Tests (140 tests)

Located in `tests/unit/`. Run with no external dependencies — all DB and LLM calls are mocked.

```bash
uv run pytest tests/unit -v
```

Key fixture: `SECURITY_SKIP_JWT_VALIDATION=true` is set in `conftest.py` so Auth0 validation is bypassed in tests.

### Smoke Tests (10 tests)

Located in `tests/smoke/`. Use FastAPI `TestClient` — no real server or DB required.

```bash
uv run pytest tests/smoke -v
```

### End-to-End Tests

Require a running server, live PostgreSQL (with `fraud_gov` data), and optionally Ollama.

```bash
uv run doppler-local &         # Start server in background
uv run e2e-local               # Run e2e script
```

### Test Data

- Synthetic data generated with `factory-boy` and `faker` in unit tests.
- Seed data via `uv run db-load-test-data` — picks real DECLINE transactions from the live DB (idempotent).

## Coding Standards

- `uv` only — never `pip install` anything.
- Doppler only — never create `.env` files.
- Use `StrEnum` not `(str, Enum)` (ruff UP042 rule).
- JSONB columns with asyncpg: always pass `json.dumps(dict)`, not a raw dict.
- asyncpg UUID values: always `str(uuid_val)` before string operations.
- Use `row_to_dict(row)` from `app/persistence/base.py` instead of `dict(row._mapping)`.
- Enums, models, and schemas follow the patterns in existing files — read before adding.
- See `AGENTS.md` for the complete no-shortcuts policy and quality gate requirements.

## Windows Notes

- Uvicorn: use the app factory pattern:
  ```bash
  uvicorn "app.main:create_app" --factory --workers 1
  ```
- Use `localhost` not `127.0.0.1` in httpx clients when running on Windows.
