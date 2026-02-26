# Card Fraud Ops Analyst Agent

Autonomous fraud analyst assistant for the Card Fraud Platform. Generates explainable risk insights, analyst-ready recommendations, and draft rule packages from existing transaction data. All final decisions remain human-controlled.

## Runtime

LangGraph agentic runtime is the active investigation path.
Quality gates are enforced via pre-commit/pre-push hooks and the documented commands below.

## Stack

- Python 3.14, FastAPI, async SQLAlchemy (asyncpg)
- Auth0 JWT authentication with scope-based authorization
- Ollama Cloud chat model adapter for planner and reasoning stages
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
doppler run --project card-fraud-platform --config local -- docker compose up -d

# Start required app services for investigation E2E
doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d --build transaction-management ops-analyst-agent

# Verify dependencies
curl http://localhost:8002/api/v1/health
curl http://localhost:8003/api/v1/health/ready

# View status
docker compose ps
```

Container context:
- Ops Agent and Transaction Management are defined in `docker-compose.apps.yml` under the `platform` profile.
- Inspect only this app container with:
  - `docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile platform ps ops-analyst-agent transaction-management`
  - `docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile platform logs -f ops-analyst-agent`

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

# Git hooks (recommended)
uv run pre-commit install --hook-type pre-commit --hook-type pre-push
uv run pre-commit run --all-files
uv run pre-commit run --all-files --hook-stage pre-push

# E2E (requires Dockerized transaction-management on 8002 and ops-analyst-agent on 8003)
doppler run --project card-fraud-platform --config local -- \
  docker compose -f ../card-fraud-platform/docker-compose.yml \
  -f ../card-fraud-platform/docker-compose.apps.yml \
  --profile platform up -d --build transaction-management ops-analyst-agent
doppler run --config local -- uv run python scripts/seed_test_scenarios.py   # Seed scenarios + manifest
uv run e2e-local                                       # Local end-to-end test
uv run pytest tests/e2e/test_scenarios.py -v           # 23-scenario suite
uv run python scripts/run_e2e_matrix_detailed.py       # 31-scenario matrix
```

## Project Structure

```
app/
  api/routes/       # FastAPI route handlers (health, monitoring, investigations, insights, recommendations)
  agent/            # LangGraph runtime (planner, executor, completion, state, registry)
  tools/            # Tool modules (context, pattern, similarity, reasoning, recommendation, rule_draft)
  services/         # Business logic services (investigation, insight, recommendation, rule_draft)
  persistence/      # Async SQLAlchemy repositories (investigation, insight, recommendation, rule_draft, audit)
  clients/          # HTTP clients (tm_client, rule_management_client, embedding_client)
  llm/              # LLM provider abstractions and routing
  core/             # Config, auth, database, logging, metrics, errors
  schemas/v1/       # Pydantic request/response schemas
cli/                # uv run entry points (doppler_local, db_setup, auth0_bootstrap, test, lint, e2e, openapi)
scripts/            # DB migration scripts, data loaders, Auth0 setup utilities
tests/
  unit/             # Unit tests (mocked DB + LLM, no external dependencies)
  smoke/            # Smoke tests (FastAPI TestClient)
db/migrations/      # SQL migration files (001+)
docs/               # Architecture, API, testing, deployment, operations documentation
```

## API Endpoints

All endpoints are prefixed with `/api/v1/ops-agent`.

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | `/transactions/{transaction_id}/insights` | `ops_agent:read` | Insights for a transaction |
| GET | `/investigations` | `ops_agent:read` | List investigations |
| POST | `/investigations/run` | `ops_agent:run` | Trigger investigation pipeline |
| GET | `/investigations/{investigation_id}` | `ops_agent:read` | Fetch investigation detail |
| POST | `/investigations/{investigation_id}/resume` | `ops_agent:run` | Resume an interrupted investigation |
| GET | `/investigations/{investigation_id}/rule-draft` | `ops_agent:read` | Fetch generated rule draft |
| GET | `/worklist/recommendations` | `ops_agent:read` | List recommendations |
| POST | `/worklist/recommendations/{recommendation_id}/acknowledge` | `ops_agent:ack` | Acknowledge or reject recommendation |

## Core Principle

Final fraud decisions and rule activation decisions are always human-controlled. The agent produces advisory outputs only. `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` must be `true` in all environments.

## Agentic Intelligence Positioning

This is an intelligence platform with agentic analysis, not autonomous adjudication.

- Agentic behavior: multi-stage investigation pipeline, vector similarity retrieval, LLM reasoning, rule-sequence safeguards, and recommendation drafting.
- Governance boundary: human analysts remain the decision authority for fraud disposition and rule activation.
- Outcome focus: improve analyst speed and consistency with explainable, auditable, evidence-backed recommendations.
- Auditability proof in API: investigation responses include `agentic_trace`, `action_plan`, and `evidence_gaps` for per-run AI/tool usage evidence.

## Documentation

- [Code Map](./docs/codemap.md) - architecture overview, modules, data flow, patterns
- [Developer Guide](./docs/02-development/developer-guide.md) - setup, workflow, runtime, and quality gates
- [Docs Index](./docs/README.md) - architecture, API, testing, deployment, operations
- [Local Setup](./docs/01-setup/local-setup.md) - step-by-step local environment setup
- [Config and Feature Flags](./docs/05-deployment/config-and-feature-flags.md) - all environment variables
- [Testing Strategy](./docs/04-testing/testing-strategy.md) - test layers and CI strategy
- [Portal Integration](./docs/03-api/portal-integration.md) - API integration map for the portal

## Test Coverage

- **Test suites**: unit, smoke, integration, and e2e
- **HTML report**: `htmlcov/index.html` (generate with command above)
- **Coverage target**: >80% line coverage, >70% branch coverage
