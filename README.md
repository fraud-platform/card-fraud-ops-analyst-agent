# Card Fraud Ops Analyst Agent

Autonomous fraud analyst assistant for the Card Fraud Platform. Generates explainable risk insights, analyst-ready recommendations, and draft rule packages from existing transaction data. All final decisions remain human-controlled.

## Status

Phase 1-3: Complete. Integration: Complete. Monitoring: Complete.
Quality gates: lint/format clean; unit/smoke suites passing (run commands below for current counts).
Latest E2E scenario suite: 23/23 passed (generated 2026-02-18 in `htmlcov/e2e-scenarios-report.html`).

## Stack

- Python 3.14, FastAPI, async SQLAlchemy (asyncpg)
- Auth0 JWT authentication with scope-based authorization
- LiteLLM for bounded LLM reasoning (Ollama local, Anthropic cloud)
- OpenTelemetry + Prometheus for observability
- PostgreSQL: reads `fraud_gov` schema, writes `ops_agent_*` tables
- Port: 8003

## Quick Start

Prerequisites: [uv](https://docs.astral.sh/uv/), [Doppler CLI](https://docs.doppler.com/docs/install-cli), Docker Desktop (for Postgres).

Important defaults:
- `OPS_AGENT_ENABLE_LLM_REASONING=true` by default.
- `VECTOR_ENABLED=true` by default.
- Ensure `VECTOR_API_BASE` and LLM provider secrets are configured in Doppler before running investigations.

### Prerequisites and Order

1. Clone sibling repositories at the same directory level:
   - `card-fraud-platform`
   - `card-fraud-transaction-management`
   - `card-fraud-rule-management`
2. Start shared platform infrastructure from `card-fraud-platform`.
3. Run `doppler setup --project card-fraud-ops-analyst-agent --config local` in this repository.
4. Verify required secrets exist (`doppler secrets --only-names`) before running `uv sync`.
5. Follow the detailed setup sequence in [`docs/01-setup/local-setup.md`](docs/01-setup/local-setup.md).

```bash
# Install dependencies
uv sync --extra dev

# Initialize database tables (ops_agent_* only)
uv run db-init

# Start dev server with secrets from Doppler
uv run doppler-local
```

The API will be available at `http://localhost:8003`. OpenAPI docs at `http://localhost:8003/docs`.

## Running as Part of Card Fraud Platform

The Ops Analyst Agent is designed to run as part of the unified `card-fraud-platform`:

```bash
# From card-fraud-platform directory
cd ../card-fraud-platform

# Start all infrastructure (Jaeger, Prometheus, Grafana, PostgreSQL, etc.)
docker compose up -d

# Start Ops Agent and other applications
doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps up -d

# View status
docker compose ps
```

Container context:
- Ops Agent is defined in `docker-compose.apps.yml` under the `apps` profile.
- Inspect only this app container with:
  - `docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps ps ops-agent`
  - `docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps logs -f ops-agent`

### Observability

| UI | URL | Purpose |
|----|-----|---------|
| **Jaeger** | http://localhost:16686 | Distributed traces - see pipeline stages & latencies |
| **Grafana** | http://localhost:3000 | Metrics dashboards (admin/admin) |
| **Prometheus** | http://localhost:9090 | Raw metrics query interface |
| **Metrics** | http://localhost:8003/api/v1/metrics | Prometheus metrics from Ops Agent (requires `X-Metrics-Token`) |

The Ops Agent exposes metrics at `/api/v1/metrics` which Prometheus scrapes. The endpoint requires `X-Metrics-Token` and validates against `METRICS_TOKEN`. Traces are sent to Jaeger via OTLP (configured in platform docker-compose).

For detailed observability documentation, see [docs/06-operations/observability.md](docs/06-operations/observability.md).

## Common Commands

```bash
# Quality gates (must all pass)
uv run ruff check app/ tests/ cli/ scripts/           # Lint (0 errors required)
uv run ruff format --check app/ tests/ cli/ scripts/  # Format check
uv run pytest tests/unit -v                            # Unit tests
uv run pytest tests/smoke -v                           # Smoke tests

# Generate HTML test coverage report
uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch
# Open report: double-click htmlcov/index.html or use file:///C:/.../htmlcov/index.html

# Development
uv run doppler-local                                   # Dev server with Doppler secrets
uv run doppler-local-test                              # Run tests with local DB

# Auth0 setup (one-time)
uv run auth0-bootstrap --yes --verbose                 # Bootstrap Auth0 API + M2M app
uv run auth0-verify                                    # Verify Auth0 configuration

# Database
uv run db-init                                         # Create ops_agent_* tables
uv run db-reset-tables                                 # Drop and recreate ops_agent_* tables
uv run db-reset-data                                   # Reset seed data
uv run db-verify                                       # Verify tables exist
uv run db-load-test-data                               # Load test data from live DB

# Code quality
uv run lint                                            # Run ruff check
uv run format                                          # Run ruff format

# E2E (requires Dockerized ops-agent on port 8003 + DB)
doppler run --config local -- uv run python scripts/seed_test_scenarios.py   # Seed scenarios + manifest
uv run e2e-local                                       # Local end-to-end test
npx playwright open htmlcov/e2e-scenarios-report.html # Review custom HTML report
```

## Project Structure

```
app/
  api/routes/       # FastAPI route handlers (investigations, insights, worklist, rule-drafts)
  agents/           # Pipeline stages: context_builder, pattern_engine, recommendation_engine,
                    #   reasoning_engine, rule_draft_engine, similarity_engine, audit_engine
                    #   *_core.py = pure logic (no DB), *.py = DB-bound adapter
  services/         # Business logic services (investigation, insight, recommendation, rule_draft)
  persistence/      # Async SQLAlchemy repositories (run, insight, recommendation, rule_draft, audit)
  clients/          # HTTP clients (rule_management_client, embedding_client)
  llm/              # LiteLLM provider, prompt templates, redaction, consistency checks
  core/             # Config, auth, database, logging, metrics, errors
  schemas/v1/       # Pydantic request/response schemas
cli/                # uv run entry points (doppler_local, db_setup, auth0_bootstrap, test, lint, e2e)
scripts/            # DB migration scripts, data loaders, Auth0 setup utilities
tests/
  unit/             # Unit tests (mocked DB + LLM, no external dependencies)
  smoke/            # Smoke tests (FastAPI TestClient)
db/migrations/      # SQL migration files (001-007)
docs/               # Architecture, API, testing, deployment, operations documentation
```

## API Endpoints

All endpoints are prefixed with `/api/v1/ops-agent`.

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | `/transactions/{transaction_id}/insights` | `ops_agent:read` | Latest insight for a transaction |
| POST | `/investigations/run` | `ops_agent:run` | Trigger investigation pipeline |
| GET | `/investigations/{run_id}` | `ops_agent:read` | Fetch investigation result |
| GET | `/worklist/recommendations` | `ops_agent:read` | List pending recommendations |
| POST | `/worklist/recommendations/{id}/acknowledge` | `ops_agent:ack` | Acknowledge a recommendation |
| POST | `/rule-drafts` | `ops_agent:draft` | Create rule draft from insight |
| POST | `/rule-drafts/{id}/export` | `ops_agent:draft` | Export draft to Rule Management |

## Core Principle

Final fraud decisions and rule activation decisions are always human-controlled. The agent produces advisory outputs only. `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` must be `true` in all environments.

## Agentic Intelligence Positioning

This is an intelligence platform with agentic analysis, not autonomous adjudication.

- Agentic behavior: multi-stage investigation pipeline, vector similarity retrieval, LLM reasoning, deterministic policy checks, and recommendation drafting.
- Governance boundary: human analysts remain the decision authority for fraud disposition and rule activation.
- Outcome focus: improve analyst speed and consistency with explainable, auditable, evidence-backed recommendations.
- Auditability proof in API: investigation responses include `agentic_trace`, `action_plan`, and `evidence_gaps` for per-run AI/tool usage evidence.

## Documentation

- [Code Map](./CODEMAP.md) — architecture overview, modules, data flow, patterns
- [Developer Guide](./DEVELOPER_GUIDE.md) — setup, workflow, architecture
- [Agent Conventions](./AGENTS.md) — quality gates, coding standards, no-shortcuts policy
- [Docs Index](./docs/README.md) — architecture, API, testing, deployment, operations
- [Local Setup](./docs/01-setup/local-setup.md) — step-by-step local environment setup
- [Config and Feature Flags](./docs/05-deployment/config-and-feature-flags.md) — all environment variables
- [Testing Strategy](./docs/04-testing/testing-strategy.md) — test layers and CI strategy
- [Portal Integration](./docs/03-api/portal-integration.md) — API integration map for the portal

## Test Coverage

- **Test suites**: unit, smoke, integration, and e2e
- **HTML report**: `htmlcov/index.html` (generate with command above)
- **Coverage target**: >80% line coverage, >70% branch coverage
