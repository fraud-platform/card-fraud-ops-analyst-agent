# Local Setup

## Prerequisites

| Tool | Purpose | Install |
|------|---------|---------|
| Docker Desktop | Runs PostgreSQL and platform infra | https://docs.docker.com/desktop/ |
| uv | Python package manager (only allowed manager) | https://docs.astral.sh/uv/ |
| Doppler CLI | Secrets manager (only allowed manager) | https://docs.doppler.com/docs/install-cli |
| Python 3.14 | Runtime (uv manages this automatically) | Managed by uv |

Sibling repositories required (clone them at the same directory level):

- `card-fraud-platform` — shared Docker Compose infra (Postgres, etc.)
- `card-fraud-transaction-management` — source of truth for `fraud_gov` transactions
- `card-fraud-rule-management` — rule package target for draft export (optional for basic local dev)

## Step-by-Step Setup

### 1. Start Platform Infrastructure

```bash
cd ../card-fraud-platform
docker compose up -d
# Wait for Postgres to be healthy before continuing
docker compose ps
```

Verify the shared `fraud_gov` database is reachable before proceeding.

### 1a. Verify Platform Container Group Health

```bash
# Infra services should be healthy (postgres, jaeger, prometheus, grafana)
docker compose ps

# Start app profile and verify ops-agent container membership/status
doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps up -d
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps ps ops-agent
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps logs --tail 50 ops-agent
```

Proceed only after shared infra services and `ops-agent` are up.

### 2. Configure Doppler

```bash
# Authenticate once per machine
doppler login

# Link this repo to its Doppler project (local config)
cd /path/to/card-fraud-ops-analyst-agent
doppler setup --project card-fraud-ops-analyst-agent --config local
```

Verify secrets are available:

```bash
doppler secrets --only-names
```

Expected secrets include: `DATABASE_URL_APP`, `DATABASE_URL_ADMIN`, `AUTH0_DOMAIN`, `AUTH0_AUDIENCE`, `AUTH0_CLIENT_ID`, `AUTH0_CLIENT_SECRET`.

### 3. Install Dependencies

```bash
uv sync --extra dev
```

This installs all runtime and dev dependencies. Never use `pip install` directly.

### 4. Run Auth0 Bootstrap (One-Time)

If this is a fresh environment and Auth0 has not been configured yet:

```bash
# Bootstrap Auth0 API + M2M client and sync to Doppler
uv run auth0-bootstrap --yes --verbose

# Verify the configuration
uv run auth0-verify
```

Note: Auth0 bootstrap must be run for `card-fraud-rule-management` first if both projects share the same tenant.

### 5. Initialize Database Tables

```bash
# Creates ops_agent_* tables in the shared Postgres instance
uv run db-init

# Dev reset: drop/recreate only ops_agent_* tables and re-apply all migrations
uv run db-reset-tables

# Verify tables were created
uv run db-verify
```

This only creates `ops_agent_*` tables. It never modifies the `fraud_gov` schema.
`db-reset-tables` is safe in shared environments because it only resets Ops Agent-owned tables.
Latest migrations include run-level audit snapshot columns (`runtime_feature_flags`, `runtime_safeguards`) on `ops_agent_runs`.

**pgvector requirement (for embeddings):**
Vector similarity is enabled by default (`VECTOR_ENABLED=true`), so the database must have the `pgvector` extension available.
If your Postgres instance does not include pgvector, the embeddings migration (`006_add_transaction_embeddings_pgvector.sql`) cannot be applied and `uv run db-verify` will fail when vector is enabled.

### 6. Configure Recommended Local Split Mode

Use cloud reasoning with local embeddings:

```bash
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=true
doppler secrets set LLM_PROVIDER=ollama/gpt-oss:20b
doppler secrets set LLM_BASE_URL=https://ollama.com

doppler secrets set VECTOR_ENABLED=true
doppler secrets set VECTOR_API_BASE=http://localhost:11434/api
doppler secrets set VECTOR_MODEL_NAME=mxbai-embed-large
```

When running the API in Docker on platform port `8003`, you can omit `VECTOR_API_BASE`.
If omitted, the service auto-resolves host Ollama via `host.docker.internal`.

Verify embedding preflight before running e2e:

```bash
doppler run -- uv run python -c "import asyncio; from app.clients.embedding_client import EmbeddingClient; r=asyncio.run(EmbeddingClient().embed('preflight')); print(len(r.embedding), r.model)"
```

Expected output: `1024 mxbai-embed-large` (dimension and model).

### 7. Load Test Data (Optional)

```bash
# Picks real DECLINE transactions from fraud_gov and creates ops_agent test records
# This operation is idempotent — safe to run multiple times
uv run db-load-test-data
```

### 8. Start the Dev Server

```bash
uv run doppler-local
```

Server starts on `http://localhost:8003`. OpenAPI docs at `http://localhost:8003/docs`.

## Ollama Setup (Optional: Fully Local LLM + Embeddings)

LLM reasoning and vector similarity are enabled by default. To run both
reasoning and embeddings locally with Ollama:

```bash
# 1. Install Ollama from https://ollama.com/download

# 2. Pull the model
ollama pull llama3.2

# 3. Verify Ollama is running
ollama run llama3.2 "ping"
```

Set the following secrets in Doppler (local config):

```bash
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=true
doppler secrets set LLM_PROVIDER=ollama_chat/llama3.2
doppler secrets set LLM_BASE_URL=http://localhost:11434
doppler secrets set LLM_API_KEY=ollama
```

Restart `uv run doppler-local` after changing Doppler secrets.

## Verification Checklist

Run each command and confirm it succeeds before starting development:

```bash
# 1. Platform database reachable
doppler run -- psql "$DATABASE_URL_APP" -c "SELECT 1;"

# 2. ops_agent_* tables exist
uv run db-verify

# 3. Lint passes
uv run ruff check app/ tests/ cli/ scripts/

# 4. Format passes
uv run ruff format --check app/ tests/ cli/ scripts/

# 5. Unit tests pass (no external dependencies needed)
uv run pytest tests/unit -v

# 6. Smoke tests pass (TestClient, no DB needed)
uv run pytest tests/smoke -v

# 7. Server starts
uv run doppler-local &
curl http://localhost:8003/health
```

Expected health response:

```json
{"status": "ok", "version": "0.1.0"}
```

## Troubleshooting

**`uv sync` fails — wrong Python version**
uv manages the Python version automatically based on `requires-python = ">=3.14"` in `pyproject.toml`. If it cannot find Python 3.14, run `uv python install 3.14`.

**`db-init` fails with permission denied**
The `DATABASE_URL_APP` user does not have DDL privileges. DB init requires `DATABASE_URL_ADMIN`. Check that the admin URL is set in Doppler and that `db-init` is picking it up (it should use `DATABASE_URL_ADMIN` by default for migrations).

**`doppler secrets` returns empty or wrong secrets**
Confirm you ran `doppler setup` in the correct directory and selected the `local` config. Run `doppler configure` to check the current project/config binding.

**Auth0 token validation fails in tests**
`SECURITY_SKIP_JWT_VALIDATION=true` must be set for tests. This is handled automatically in `tests/conftest.py`. If running manually, export the variable before running pytest.

**`asyncpg` UUID errors in DB queries**
Always convert UUID objects to strings with `str(uuid_val)` before using them in string contexts. Use `row_to_dict(row)` from `app/persistence/base.py` when reading rows — it handles UUID conversion at the persistence boundary.

**Server fails on Windows with multiple workers**
Use `--workers 1` with the factory pattern:
```bash
uvicorn "app.main:create_app" --factory --workers 1 --port 8003
```
