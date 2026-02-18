# AGENTS.md - Card Fraud Ops Analyst Agent

Canonical instructions for all coding and documentation agents working in this repository. This file is the single source of truth for agent behavior, quality standards, and implementation rules.

## New Coding Agent Checklist

Before making changes, complete this sequence:

1. Read `README.md` and `docs/README.md` to understand platform context and project entry points.
2. Follow `docs/01-setup/local-setup.md` for environment setup and sibling repo expectations.
3. Install dependencies with `uv sync --extra dev`.
4. Confirm quality gates command is available and run it before and after changes:
   `uv run ruff check app/ tests/ cli/ scripts/ && uv run ruff format --check app/ tests/ cli/ scripts/ && uv run pytest tests/unit tests/smoke -v`
5. Use `docs/06-operations/observability.md` validation checklist when changes affect logging, metrics, or tracing.

## No-Shortcuts Policy

**Every agent MUST follow this file exactly. No shortcuts, no skipping steps, no "we'll fix it later" exceptions.** Deviations from the implementation plan require explicit human approval before proceeding.

- Do NOT skip lint checks to save time.
- Do NOT skip tests to unblock yourself.
- Do NOT hardcode secrets or connection strings.
- Do NOT use `.env` files. Ever.
- Do NOT use `pip`. Ever. Use `uv` exclusively.
- Do NOT drop the `fraud_gov` schema. Only drop this project's tables.
- Do NOT merge code that fails any quality gate.

---

## Repository Intent

This repository implements the `card-fraud-ops-analyst-agent` — an autonomous fraud analyst assistant that reads transaction data from `fraud_gov`, runs deterministic evidence analysis, and generates advisory insights and recommendations for human analysts. Human analysts retain final authority.

**Current phase**: Phase 1-3 complete — deterministic core + hybrid reasoning enhancements implemented.

---

## Quality Gates (MANDATORY)

Every code change MUST pass ALL quality gates before it can be considered complete. No exceptions.

### Gate 1: Lint (Zero Errors)

```bash
uv run ruff check app/ tests/
```

Must produce **zero errors**. Fix all issues before proceeding. Do not use `# noqa` unless absolutely justified and documented.

### Gate 2: Format (Clean)

```bash
uv run ruff format --check app/ tests/
```

Must report all files already formatted. If not, run `uv run ruff format app/ tests/` and include formatted files in your change.

### Gate 3: Unit Tests (All Pass)

```bash
uv run pytest tests/unit -v
```

All unit tests must pass. Zero failures, zero errors. Unit tests are fast (no DB required) and there is no excuse for skipping them.

### Gate 4: Smoke Tests (All Pass)

```bash
uv run pytest tests/smoke -v
```

All smoke tests (TestClient-based API tests) must pass. These validate API endpoint shapes and response contracts.

### Gate 5: Integration Tests (All Pass — When DB Available)

```bash
doppler run --config local-test -- uv run pytest tests/integration -v
```

Integration tests require a running database. When a database is available, all integration tests must pass.

### Gate 6: Type Safety

All Pydantic models use strict validation. All function signatures use type hints. All return types are annotated.

### Verification Command (Run All Gates)

```bash
uv run ruff check app/ tests/ cli/ scripts/ && uv run ruff format --check app/ tests/ cli/ scripts/ && uv run pytest tests/unit tests/smoke -v
```

Expected: 0 lint errors, format check clean, and all unit/smoke tests passing in the current repository state.

### HTML Coverage Report

Generate comprehensive HTML test coverage report:

```bash
uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch
```

Open report: Double-click `htmlcov/index.html` or use `file:///C:/.../htmlcov/index.html`

Report includes:
- Test execution results (pass/fail/skip per test)
- Coverage percentages per module
- Line-by-line coverage highlighting
- Branch coverage metrics

---

## Tooling Rules

### Package Manager: uv ONLY

```bash
uv sync                    # Install dependencies
uv sync --extra dev        # Install with dev dependencies
uv add <package>           # Add a dependency
uv run <command>           # Run any command
```

**NEVER use pip.** Not `pip install`, not `pip freeze`, not `python -m pip`. The project uses `uv` exclusively with `pyproject.toml` and `uv.lock`.

### Secrets Management: Doppler ONLY

All secrets are injected via Doppler at runtime. No `.env` files, no hardcoded credentials, no secrets in Git.

```bash
uv run doppler-local          # Dev server with Doppler secrets
uv run doppler-local-test     # Tests with local Docker DB
uv run doppler-test           # Tests against Neon test branch
uv run doppler-prod           # Tests against Neon prod branch
```

**Doppler project**: `card-fraud-ops-analyst-agent`
**Environments**: `local`, `local-test`, `test`, `prod`

**Required Secrets (Doppler local config):**

| Secret | Description |
|--------|-------------|
| `APP_ENV` | Environment (`local`, `test`, `prod`) |
| `APP_NAME` | `card-fraud-ops-analyst-agent` |
| `DATABASE_URL_APP` | PostgreSQL connection (`postgresql://...@localhost:5432/fraud_gov`) |
| `AUTH0_DOMAIN` | `dev-gix6qllz7yvs0rl8.us.auth0.com` |
| `AUTH0_AUDIENCE` | `https://fraud-ops-analyst-agent-api` |
| `AUTH0_ISSUER` | `https://dev-gix6qllz7yvs0rl8.us.auth0.com/` |
| `AUTH0_MGMT_DOMAIN` | Same as AUTH0_DOMAIN (for bootstrap) |
| `AUTH0_MGMT_CLIENT_ID` | Management M2M client ID (shared platform) |
| `AUTH0_MGMT_CLIENT_SECRET` | Management M2M client secret (shared platform) |
| `AUTH0_API_NAME` | `Fraud Ops Analyst Agent API` |
| `AUTH0_M2M_APP_NAME` | `Fraud Ops Analyst Agent M2M` |
| `METRICS_TOKEN` | Shared secret required by `/api/v1/metrics` (`X-Metrics-Token`) |
| `SECURITY_SKIP_JWT_VALIDATION` | `true` for local dev only |
| `SERVER_PORT` | `8003` |

**Auth0 Bootstrap Order:**
1. Run `card-fraud-rule-management` bootstrap FIRST (creates shared roles)
2. Then run `uv run auth0-bootstrap --yes --verbose` in this project

### Linter/Formatter: Ruff

Configuration in `pyproject.toml` under `[tool.ruff]` and `[tool.ruff.lint]`:
- Line length: 100
- Target: Python 3.14
- Rules: E, F, I, N, W, UP, B (errors, pyflakes, isort, naming, warnings, upgrades, bugbear)
- Per-file ignores for tests and route files

---

## Database Isolation (CRITICAL)

The `fraud_gov` schema is **shared** across multiple projects:
- `card-fraud-rule-management` owns rule tables
- `card-fraud-transaction-management` owns transaction tables
- `card-fraud-ops-analyst-agent` owns `ops_agent_*` tables

### This Project's Tables ONLY

```
ops_agent_runs
ops_agent_insights
ops_agent_evidence
ops_agent_recommendations
ops_agent_rule_drafts
ops_agent_audit_log
ops_agent_transaction_embeddings
```

### Safe Reset Commands

```bash
# Drop and recreate ONLY this project's tables
doppler run --config local -- uv run python -m scripts.db_reset_tables

# Clear data from this project's tables (keep schema)
doppler run --config local -- uv run python -m scripts.db_reset_data
```

### NEVER DO THIS

```sql
DROP SCHEMA fraud_gov CASCADE;  -- DESTROYS ALL PROJECTS' DATA
```

Always use table-specific DROP/CREATE statements scoped to `ops_agent_*` tables.

---

## Architecture Guardrails

- Transaction Management (`fraud_gov`) is source of truth for all transaction data.
- Human analysts remain final authority on all fraud decisions.
- Agent outputs are **advisory and draft-oriented** only.
- No direct rule activation from this service.
- No raw PAN data handling — tokenized `card_id` only.
- No mutation of TM source-of-truth tables.
- Every recommendation and action is auditable.

### Core/Adapter Split (ENFORCED)

Agent modules follow a strict split:

- **`*_core.py`** (Pure logic): Zero database access. Pure functions on in-memory data. Fully deterministic. Fast unit-testable.
- **`*.py`** (DB-bound adapter): Reads DB, calls core functions, writes results back.

This split enables fast determinism tests and clear separation of concerns. Do NOT add database calls to `*_core.py` files.

### Security Guardrails

- Treat all outbound LLM context as policy-controlled.
- Use pseudonymous stable IDs for correlation.
- Block direct personal data fields from prompt payloads.
- Preserve auditability for recommendations and human actions.

---

## Project Structure

```
card-fraud-ops-analyst-agent/
├── CLAUDE.md                          # Points to AGENTS.md
├── AGENTS.md                          # THIS FILE - canonical instructions
├── pyproject.toml                     # Project config, deps, scripts, tool config
├── uv.lock                           # Locked dependencies
├── Dockerfile                         # Multi-stage build with uv
├── .dockerignore
├── .gitignore
├── cli/
│   ├── __init__.py
│   ├── _constants.py                  # DOPPLER_PROJECT, PROJECT_PREFIX
│   ├── _runner.py                     # run(), run_doppler() utilities
│   ├── auth0_bootstrap.py             # uv run auth0-bootstrap
│   ├── auth0_verify.py                # uv run auth0-verify
│   ├── db_setup.py                    # uv run db-init, db-reset-*, db-verify
│   ├── dev.py                         # uv run dev
│   ├── doppler_local.py               # uv run doppler-local, doppler-test, etc.
│   ├── lint.py                        # uv run lint, uv run format
│   └── test.py                        # uv run test, test-smoke, test-all
├── app/
│   ├── __init__.py
│   ├── main.py                        # create_app(), lifespan, routers, error handlers
│   ├── core/
│   │   ├── config.py                  # Pydantic settings per concern
│   │   ├── auth.py                    # Auth0 JWT, scopes, require_scope()
│   │   ├── database.py                # Async SQLAlchemy engine + session
│   │   ├── dependencies.py            # Annotated type aliases for auth
│   │   ├── errors.py                  # OpsAgentError hierarchy
│   │   ├── logging.py                 # structlog setup
│   │   └── metrics.py                 # Prometheus counters/histograms
│   ├── api/routes/
│   │   ├── health.py                  # /health, /health/ready, /health/live
│   │   ├── investigations.py          # POST /investigations/run, GET /{run_id}
│   │   ├── insights.py               # GET /transactions/{txn_id}/insights
│   │   ├── recommendations.py        # GET /worklist/recommendations, POST /{id}/acknowledge
│   │   └── rule_drafts.py            # POST /rule-drafts, POST /{id}/export
│   ├── schemas/v1/
│   │   ├── common.py                  # Enums, ApiError, PaginatedResponse
│   │   ├── health.py                  # Health/Ready responses
│   │   ├── investigations.py          # Run request/response
│   │   ├── insights.py               # Insight/evidence models
│   │   ├── recommendations.py        # Recommendation models
│   │   └── rule_drafts.py            # Rule draft models
│   ├── persistence/
│   │   ├── base.py                    # BaseCursor (keyset pagination)
│   │   ├── context_reader.py          # READ-ONLY queries on TM tables
│   │   ├── run_repository.py          # ops_agent_runs CRUD
│   │   ├── insight_repository.py      # ops_agent_insights + evidence CRUD
│   │   ├── recommendation_repository.py # ops_agent_recommendations CRUD
│   │   ├── rule_draft_repository.py   # ops_agent_rule_drafts CRUD
│   │   └── audit_repository.py        # ops_agent_audit_log (append-only)
│   ├── agents/
│   │   ├── context_builder_core.py    # PURE: feature extraction
│   │   ├── context_builder.py         # DB-bound: reads TM, calls core
│   │   ├── pattern_engine_core.py     # PURE: anomaly scoring
│   │   ├── pattern_engine.py          # DB-bound: calls core scoring
│   │   ├── similarity_engine_core.py  # PURE: threshold evaluation
│   │   ├── similarity_engine.py       # DB-bound: SQL overlap, calls core
│   │   ├── recommendation_engine_core.py # PURE: policy rules
│   │   ├── recommendation_engine.py   # DB-bound: generates + persists
│   │   ├── reasoning_engine.py        # LLM reasoning stage with deterministic fallback
│   │   ├── rule_draft_engine.py       # Rule draft generation/export adapter
│   │   ├── audit_engine.py            # Thin wrapper around audit_repository
│   │   └── pipeline.py               # Linear orchestrator with OTel spans
│   ├── services/
│   │   ├── investigation_service.py   # Orchestrates pipeline
│   │   ├── insight_service.py         # Read insight snapshots
│   │   ├── recommendation_service.py  # Worklist query, acknowledge/reject
│   │   ├── rule_draft_service.py      # Create/export draft (stub Phase 1)
│   │   └── audit_service.py           # Emit audit log entries
│   └── utils/
│       ├── clock.py                   # utc_now() helper
│       └── idempotency.py            # SHA-256 idempotency keys
├── scripts/
│   ├── __init__.py
│   ├── setup_database.py             # DB init (create tables)
│   ├── verify_database.py            # DB verify (check tables exist)
│   ├── reset_tables.py               # Drop/create ops_agent_* tables ONLY
│   ├── reset_data.py                 # Truncate ops_agent_* tables ONLY
│   ├── setup_auth0.py                # Auth0 bootstrap (idempotent)
│   ├── verify_auth0.py               # Auth0 verification
│   ├── run_dev.py                    # Dev server launcher
│   └── run_tests.py                  # Test runner
├── db/
│   ├── ops_agent_schema.sql           # Combined reference DDL
│   └── migrations/
│       ├── 001_create_ops_agent_tables.sql
│       ├── 002_create_ops_agent_indexes.sql
│       ├── 003_create_ops_agent_constraints.sql
│       └── 004_create_ops_agent_grants.sql
└── tests/
    ├── conftest.py                    # Env vars, mock tokens, mock_session
    ├── unit/                          # Fast, no DB
    ├── integration/                   # Requires DB
    ├── smoke/                         # TestClient API tests
    └── e2e/                           # Full flow tests
```

---

## Implementation Plan Reference

See `docs/phase-1-implementation-plan.md` for the full Phase 1 plan with 13 ordered steps.

### Phase 1 Checklist (ALL COMPLETE)

- [x] Step 1: Project configuration (pyproject.toml, .gitignore, .dockerignore)
- [x] Step 2: Core infrastructure (config, errors, database, logging, auth, dependencies, metrics)
- [x] Step 3: Utilities (idempotency, clock)
- [x] Step 4: Schemas (v1 API DTOs — 7 schema files, Pydantic V2)
- [x] Step 5: Persistence layer (7 repositories with real SQL, keyset pagination, idempotency)
- [x] Step 6: Agent core (4 pure logic modules, zero DB access)
- [x] Step 7: Agent DB-bound modules + pipeline (linear orchestrator, 6 stages)
- [x] Step 8: Services (investigation, insight, recommendation, audit + stubs for Phase 2/3)
- [x] Step 9: API routes (7 endpoints with auth scopes)
- [x] Step 10: Application entry point (create_app factory, lifespan, OTel)
- [x] Step 11: Database migrations (4 files: tables, indexes, constraints, grants)
- [x] Step 12: Dockerfile + platform integration (multi-stage, uv, non-root, health check)
- [x] Step 13: Tests (all required suites passing in CI/local quality gates)

### Phase 1 Quality Fixes (Completed)

- [x] Fix ruff config (deprecated top-level settings)
- [x] Fix all lint errors (import sorting, unused variables, StrEnum migration)
- [x] Fix smoke test failures (auth dependency injection — Annotated type aliases)
- [x] Fix Dockerfile (no pip, use official uv image from ghcr.io/astral-sh/uv)
- [x] Add Doppler integration (doppler setup, removed .env.example)
- [x] Add database reset scripts (scripts/reset_tables.py, scripts/reset_data.py)
- [x] Configure .gitignore for Doppler-only policy
- [x] Verify all quality gates pass (lint, format, unit/smoke suites)

---

## Pyproject.toml Script Commands

Standard commands available via `uv run <command>`:

```bash
# Development (always via Doppler)
uv run dev                     # Dev server (plain, no Doppler)
uv run doppler-local           # Dev server with Doppler secrets
uv run doppler-local-test      # Tests with local Docker DB
uv run doppler-test            # Tests against Neon test DB
uv run doppler-prod            # Tests against Neon prod

# Auth0
uv run auth0-bootstrap --yes --verbose   # Bootstrap Auth0 API + M2M
uv run auth0-verify                       # Verify Auth0 configuration

# Database
uv run db-init                 # Create ops_agent_* tables (local)
uv run db-init-test            # Create ops_agent_* tables (test)
uv run db-verify               # Verify tables exist (local)
uv run db-verify-test          # Verify tables exist (test)
uv run db-reset-tables         # Drop and recreate ops_agent_* tables (local)
uv run db-reset-data           # Truncate ops_agent_* tables (local)

# Testing
uv run test                    # Unit tests
uv run test-smoke              # Smoke tests
uv run test-all                # All tests

# Code Quality
uv run lint                    # ruff check app/ tests/
uv run format                  # ruff format app/ tests/
```

---

## Docker

Multi-stage build pattern:
- Builder stage: `python:3.14-slim` with uv from official image
- Runtime stage: `python:3.14-slim` with curl, non-root `appuser`
- Port: 8003
- Health check: `curl -f http://localhost:8003/api/v1/health`

---

## Coding Standards

### Python Style

- Python >= 3.14
- Line length: 100
- Type hints on all function signatures and return types
- Frozen dataclasses for pure data structures
- Pydantic V2 models for API DTOs (frozen where appropriate)
- Raw SQL via `sqlalchemy.text()` — no ORM models
- Repositories return `dict[str, Any]`
- `asyncpg` driver for async database operations

### Import Order (Enforced by Ruff)

1. Standard library
2. Third-party packages
3. Local application imports

### Naming Conventions

- Files: lowercase with underscores (`context_builder_core.py`)
- Docs: lowercase kebab-case (`local-setup.md`)
- Exceptions: `README.md`, `CLAUDE.md`, `AGENTS.md`, `DEVELOPER_GUIDE.md`
- Classes: PascalCase
- Functions/variables: snake_case
- Constants: UPPER_SNAKE_CASE
- API paths: lowercase with hyphens (`/rule-drafts`)

### Error Handling

Use the `OpsAgentError` hierarchy from `app/core/errors.py`:
- `ValidationError` -> 400
- `NotFoundError` -> 404
- `ForbiddenError` -> 403
- `ConflictError` -> 409
- `DependencyError` -> 502
- `InternalError` -> 500

### ID Generation

- Use `uuid.uuid7()` from Python 3.14 stdlib
- Never use database-generated UUIDs

### Auth Pattern

- Auth0 JWT with scopes: `ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `ops_agent:draft`, `ops_agent:admin`
- Use `require_scope()` dependency factory
- Local bypass via `SECURITY_SKIP_JWT_VALIDATION=true`

---

## When Implementation Changes

1. Update AGENTS.md if architectural decisions change.
2. Update relevant docs in the same change.
3. Regenerate OpenAPI if API surface changes.
4. Run all quality gates.
5. Never commit code that fails any gate.

---

## Change Rules

- **Plan deviations require explicit human approval** before implementation.
- Keep changes minimal, explicit, and reversible.
- Preserve existing behavior unless a change is specifically requested.
- No new tooling without clear justification.
- No speculative abstractions or premature optimization.
- Every PR must pass all quality gates listed above.

---

## Learnings & Hard-Won Patterns

**Always update AGENTS.md with learnings from every session.** This prevents repeating mistakes.

### HTML Test Coverage Reports
- Generate with: `uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch`
- Report location: `htmlcov/index.html` at project root
- Open in browser: double-click file or use `file:///C:/.../htmlcov/index.html`
- Includes test execution, coverage percentages, line-by-line highlighting, branch coverage
- Useful for identifying untested code before committing changes

### Database Reset Script (`scripts/reset_tables.py`)
- **Must use `DATABASE_URL_ADMIN`** for DDL operations (drops, creates, indexes, constraints)
- `DATABASE_URL_APP` user (`fraud_gov_app_user`) does NOT have DDL privileges
- DROP TABLE must use schema prefix: `DROP TABLE IF EXISTS fraud_gov.{table} CASCADE`
- Migrations must run in **per-file transactions** with **SAVEPOINT per statement** - a single transaction across all files causes cascading failures when one statement fails
- The `_extract_statements()` helper strips leading comment-only lines before splitting on `;`

### Run-Level Audit Snapshots
- Persist run-time controls on `ops_agent_runs` so detail views reflect the execution state, not current environment config.
- Required JSONB columns: `runtime_feature_flags`, `runtime_safeguards`.
- Keep vector audit semantics explicit in payloads/traces:
  - `vector_feature_enabled` = feature flag state for the run
  - `vector_stage_executed` = similarity stage executed with vector path
  - `vector_match_count` = number of vector matches returned
- Evidence gap rule: if `vector_stage_executed` is true and `vector_match_count == 0`, include the no-close-match gap even for LOW-risk scenarios.

### SQL Aliases for Schema Compatibility
- DB columns use prefixed names (`recommendation_type`, `recommendation_payload`, `insight_summary`)
- Pydantic schemas use short names (`type`, `payload`, `summary`)
- **Always use SQL aliases** in RETURNING and SELECT clauses: `recommendation_type AS type`, `recommendation_payload AS payload`, `insight_summary AS summary`
- When renaming dict keys via SQL aliases, update ALL consumers (engines, services, tests)

### Response Mapping Convention
- Repository dicts → route handlers → Pydantic schemas must align
- If a schema field doesn't exist in DB (like `priority`), give it a **default value** in the schema (`priority: int = 0`)
- The `get_investigation` endpoint must reconstruct full response from run record + associated insights/recommendations (not just return the run dict)

### asyncpg UUID Serialization
- asyncpg returns `uuid.UUID` objects for UUID columns, NOT strings
- Pydantic schemas expect `str` for ID fields — causes `ResponseValidationError` at runtime
- Fix: `row_to_dict()` helper in `app/persistence/base.py` converts UUID→str at the persistence boundary
- ALL repositories must use `row_to_dict(row)` instead of `dict(row._mapping)`
- This is NOT caught by unit tests (mocks return strings) — only caught by e2e tests with real DB

### Script Schema Prefixes
- ALL scripts (`reset_tables.py`, `reset_data.py`) must use `fraud_gov.` prefix in SQL
- Without prefix, PostgreSQL uses `search_path` which may not find `fraud_gov` tables
- Pattern: `TRUNCATE TABLE fraud_gov.{table}`, `DROP TABLE IF EXISTS fraud_gov.{table}`

### API Route Prefixes
- Health: `/api/v1/health`
- All ops-agent routes: `/api/v1/ops-agent/...`
- Worklist: `/api/v1/ops-agent/worklist/recommendations`
- Acknowledge: `/api/v1/ops-agent/worklist/recommendations/{id}/acknowledge`
- On Windows: use `localhost` not `127.0.0.1` for httpx connections

### Test Updates When Changing Dict Keys
- When SQL aliases change dict keys, grep ALL test files for the old key name
- Recommendation dicts: use `type` and `payload` (not `recommendation_type`, `recommendation_payload`)
- Insight dicts: use `summary` (not `insight_summary`)
- Core module dataclasses keep their original field names (`RecommendationCandidate.recommendation_type`) — only DB response dicts change

### SQL Optional Filter Safety
- When building SQL with optional filters and `OR` branches, avoid patterns like `(:param IS NULL OR col = :param)` combined with `OR` — it can turn into an unintended match-all.
- Prefer explicit guards per branch: `(:param IS NOT NULL AND col = :param)` and wrap `OR` groups in parentheses before adding `AND` constraints (exclude-id, time windows).

### Pattern Engine Core Safety
- Card-testing amount ladders must be validated in chronological order. Never sort amounts before checking monotonic increase.
- Similarity overall score must average by actual match count (`len(top_matches)`), not a fixed divisor.

### E2E Scenario Integrity
- Scenario seed functions must return an inserted `transaction_id` (especially sequence seeds with many generated IDs).
- TM API dependency failures in E2E setup (non-200 from `/api/v1/transactions`) must fail the test immediately, not downgrade to skip/pass.
- If scenario seed data is absent, explicitly `pytest.skip(...)` the scenario; never return success from setup fallback paths.
- Pattern validation stages must fail hard when required scenario signals are missing; warning-only checks create false-green reports.
- Low-risk scenarios need an upper severity guard (`LOW`) in addition to minimum checks.

### Tracing Context Hygiene
- Clear request-scoped tracing context (`request_id`, `traceparent`) after every HTTP request to prevent cross-request leakage.
- Always set traceparent context per request, including explicit `None`, so stale values are not reused.
- Keep smoke/unit coverage for `X-Request-ID` response propagation and post-request context reset.

### Platform DSN Compatibility
- Platform compose may pass SQLAlchemy pool settings inside `DATABASE_URL_*` query strings (for example `?pool_size=20&max_overflow=10`).
- `asyncpg` treats unknown DSN query params as connect kwargs and raises runtime `TypeError` (`unexpected keyword argument 'pool_size'`).
- Strip engine-only keys (`pool_size`, `max_overflow`, `pool_timeout`, `pool_recycle`) from DSN URLs before creating async/sync engine URLs.

### Script DSN Normalization
- All DB scripts (setup/reset/verify/load/seed) must normalize `DATABASE_URL_*` through shared URL helpers before connecting.
- Never pass raw `DATABASE_URL_*` with SQLAlchemy pool query parameters directly to `asyncpg` or `psycopg`.

### Long-Running Pipeline Transactions
- Commit a transaction checkpoint before long external stages (LLM/embedding/network waits) so DB connections return to the pool.
- Persist the run row early in investigation flow; avoid keeping a single transaction open for the entire pipeline duration.

### OTEL Environment Mapping
- Platform containers use standard OpenTelemetry env vars: `OTEL_EXPORTER_OTLP_ENDPOINT` and `OTEL_EXPORTER_OTLP_INSECURE`.
- App config must map/fallback to these names; relying only on `OTEL_OTLP_ENDPOINT` leaves tracing disabled even when Jaeger is available.

### Idempotent Replay Refresh
- For insight/recommendation persistence keyed by `idempotency_key`, use `ON CONFLICT ... DO UPDATE` for mutable analysis fields instead of `DO NOTHING`.
- `DO NOTHING` preserves stale severity/summary/payload when deterministic logic changes and the same scenario is replayed.

### Time-Anchored Window Features
- `compute_all_windows(...)` must use the investigated transaction timestamp as the reference anchor, not wall-clock `datetime.now()`.
- Window filters must exclude future transactions relative to the anchor (`ts <= anchor`) to avoid inflated or inconsistent velocity signals.

### Hybrid E2E Latency Gate
- Acceptance KPI `run_investigation_p95_ms` is calibrated for hybrid deterministic+LLM execution at `<= 30000ms` in local/platform E2E environments.
- Keep detail fetch KPI strict (`detail_fetch_p95_ms <= 4000ms`) because it is DB/API-bound and should stay fast.

### Local E2E Port Isolation
- Default service port is `8003` for platform integration and local E2E.
- Local E2E and scenario-audit runs must execute against the Dockerized ops-agent on `http://localhost:8003`.
- Fail fast if port `8003` is not owned by an ops-agent Docker container; do not run E2E against ad-hoc local `uvicorn` processes.
- If `8003` is occupied by another service, stop the conflicting process/container and restart platform apps.

### Agentic Detail Reconstruction
- `GET /investigations/{run_id}` must reconstruct stage context for `action_plan` from persisted evidence and run metadata, not pass `None` placeholders.
- Structured evidence envelopes store pattern/similarity signals in `evidence_payload.supporting_data`; detail-time planners/traces must parse that shape.

### LLM Status Consistency
- Recommendation payload `llm_status` must align with run-level semantics (`disabled` when feature off, `skipped` when enabled but no reasoning result, `fallback` on error).
- Avoid ambiguous statuses like `not_requested` when run-level status is already explicit.

### LLM Provider Routing
- Do not auto-route `gpt-*` model names to Ollama.
- Route to Ollama only when provider prefix is explicit (`ollama/`, `ollama_chat/`) or `LLM_BASE_URL` targets an Ollama host.

### Doppler Integration Config Fallback
- Prefer `doppler run --config local-test -- uv run pytest tests/integration -v` when `local-test` exists.
- If `local-test` is not present in the Doppler workspace, run integration tests with `--config local` and record the exact run date/result in docs.

### E2E KPI Scope Definition
- Keep `fraud_recall_medium_plus` scoped to high-confidence fraud scenarios (card testing, velocity burst, cross-merchant spread, high-decline ratio).
- Do not include mixed/advisory scenarios (for example likely-fraud) in recall denominator; they are validated separately via scenario invariants.

### E2E Evidence Rendering Shape
- Investigation/detail APIs return evidence with nested `evidence_payload` fields.
- E2E HTML reporter must extract `category`, `strength`, and `description` from `evidence_payload` (fallback to top-level only when present).
- If evidence is absent, render `evidence_summary` as an empty list (`[]`), not placeholder objects with blank fields.

### Local E2E Process Hygiene
- E2E assertions can fail against stale runtime logic if a long-lived `uvicorn` process on `8003` was started before recent code changes.
- Before calibrating fraud-quality regressions, confirm the active `8003` process command line and restart the service from current workspace code.
- After restart, rerun the failing scenario subset first, then full `tests/e2e/test_scenarios.py` to validate KPI gates.
---

## Trust Hierarchy

When sources conflict, trust in this order:
1. Code in `app/`, `scripts/`, `tests/`
2. `pyproject.toml` configuration
3. `AGENTS.md` (this file)
4. `docs/` documentation
5. External references
