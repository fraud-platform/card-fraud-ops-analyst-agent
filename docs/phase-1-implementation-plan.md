# Card Fraud Ops Analyst Agent - Phase 1 Implementation Plan

## Context

The `card-fraud-ops-analyst-agent` repository currently contains only architecture documentation (40+ docs) and no implementation code. The project is an autonomous fraud analyst assistant that reads transaction data from `fraud_gov`, runs deterministic evidence analysis, and generates advisory insights/recommendations for human analysts. Human analysts retain final authority.

This plan covers **Phase 1 (Foundation and Deterministic Core)** - the first of three phases defined in `docs/archive/implementation-roadmap.md`. Phase 2 (analyst actions + rule draft handoff) and Phase 3 (LLM hybrid enablement) will follow after Phase 1 gates pass.

### Pattern Sources
- **Infrastructure patterns**: `card-fraud-transaction-management` (FastAPI app factory, async SQLAlchemy, Auth0 JWT, pydantic-settings, structlog, OpenTelemetry)
- **Agent architecture**: `card-fraud-analytics-agent` (core/adapter split for pure-logic vs DB-bound modules, UUIDv7, frozen API DTOs)
- **Platform conventions**: `card-fraud-platform` (Docker compose, `card-fraud-network`, port allocation, Doppler secrets, health checks)

---

## Directory Structure

```
card-fraud-ops-analyst-agent/
├── pyproject.toml                      # REPLACE (full deps + pytest config)
├── Dockerfile                          # NEW
├── .dockerignore                       # NEW
├── .gitignore                          # NEW
├── app/
│   ├── __init__.py
│   ├── main.py                         # create_app(), lifespan, telemetry, exception handlers
│   ├── core/
│   │   ├── __init__.py
│   │   ├── config.py                   # BaseSettings per concern, composed Settings, @lru_cache
│   │   ├── auth.py                     # Auth0 JWT, JWKS cache, scopes, require_scope()
│   │   ├── database.py                 # create_async_engine, async_sessionmaker, get_session
│   │   ├── dependencies.py             # Annotated type aliases: RequireOpsRead, RequireOpsRun, etc.
│   │   ├── errors.py                   # OpsAgentError hierarchy + ERROR_STATUS_MAP
│   │   ├── logging.py                  # structlog setup
│   │   └── metrics.py                  # Prometheus counters/histograms
│   ├── api/
│   │   ├── __init__.py
│   │   └── routes/
│   │       ├── __init__.py
│   │       ├── health.py               # /health, /health/ready, /health/live
│   │       ├── investigations.py       # POST /investigations/run, GET /{run_id}
│   │       ├── insights.py             # GET /transactions/{txn_id}/insights
│   │       ├── recommendations.py      # GET /worklist/recommendations, POST /{id}/acknowledge
│   │       └── rule_drafts.py          # POST /rule-drafts, POST /{id}/export
│   ├── schemas/
│   │   ├── __init__.py
│   │   └── v1/
│   │       ├── __init__.py
│   │       ├── common.py               # Enums (Severity, RunMode, RecommendationStatus, etc.), ApiError
│   │       ├── health.py               # HealthResponse, ReadyResponse
│   │       ├── investigations.py       # RunRequest, RunResponse, DetailResponse
│   │       ├── insights.py             # InsightDetail, EvidenceItem, InsightListResponse
│   │       ├── recommendations.py      # AcknowledgeRequest, RecommendationDetail, ListResponse
│   │       └── rule_drafts.py          # CreateRequest, ExportRequest, RuleDraftResponse
│   ├── persistence/
│   │   ├── __init__.py
│   │   ├── base.py                     # BaseCursor (keyset pagination)
│   │   ├── context_reader.py           # READ-ONLY queries on TM tables
│   │   ├── insight_repository.py       # ops_agent_insights + evidence CRUD
│   │   ├── recommendation_repository.py # ops_agent_recommendations CRUD + worklist query
│   │   ├── rule_draft_repository.py    # ops_agent_rule_drafts CRUD
│   │   ├── run_repository.py           # ops_agent_runs CRUD
│   │   └── audit_repository.py         # ops_agent_audit_log (append-only)
│   ├── services/
│   │   ├── __init__.py
│   │   ├── investigation_service.py    # Orchestrates pipeline, checks feature flags
│   │   ├── insight_service.py          # Read insight snapshots
│   │   ├── recommendation_service.py   # Worklist query, acknowledge/reject + audit
│   │   ├── rule_draft_service.py       # Create/export draft (stub in Phase 1)
│   │   └── audit_service.py            # Emit audit log entries
│   ├── agents/
│   │   ├── __init__.py
│   │   ├── context_builder_core.py     # PURE: feature extraction, window stats, signal extraction
│   │   ├── context_builder.py          # DB-bound: reads TM tables, calls core
│   │   ├── pattern_engine_core.py      # PURE: anomaly scoring, severity classification
│   │   ├── pattern_engine.py           # DB-bound: calls core scoring
│   │   ├── similarity_engine_core.py   # PURE: threshold evaluation, freshness weighting
│   │   ├── similarity_engine.py        # DB-bound: SQL overlap query, calls core
│   │   ├── recommendation_engine_core.py # PURE: policy rules, candidate generation
│   │   ├── recommendation_engine.py    # DB-bound: generates + persists recommendations
│   │   ├── reasoning_engine.py         # STUB: returns None (Phase 3)
│   │   ├── rule_draft_engine.py        # STUB: raises NotImplementedError (Phase 2)
│   │   ├── audit_engine.py             # Thin wrapper around audit_repository
│   │   └── pipeline.py                 # Linear orchestrator with OTel spans
│   ├── utils/
│   │   ├── __init__.py
│   │   ├── uuid7.py                    # UUIDv7 generator
│   │   ├── idempotency.py              # Idempotency key computation (SHA-256)
│   │   └── clock.py                    # utc_now() helper
│   └── graph/
│       └── __init__.py                 # Reserved for Phase 3 LangGraph
├── db/
│   ├── ops_agent_schema.sql            # Combined reference DDL
│   └── migrations/
│       ├── 001_create_ops_agent_tables.sql
│       ├── 002_create_ops_agent_indexes.sql
│       ├── 003_create_ops_agent_constraints.sql
│       └── 004_create_ops_agent_grants.sql
└── tests/
    ├── __init__.py
    ├── conftest.py                     # Env vars, mock tokens, mock_session fixture
    ├── unit/
    │   ├── __init__.py
    │   ├── test_config.py
    │   ├── test_errors.py
    │   ├── test_uuid7.py
    │   ├── test_idempotency.py
    │   ├── test_context_builder_core.py
    │   ├── test_pattern_engine_core.py
    │   ├── test_similarity_engine_core.py
    │   ├── test_recommendation_engine_core.py
    │   ├── test_investigation_schemas.py
    │   ├── test_recommendation_schemas.py
    │   ├── test_auth_scopes.py
    │   └── test_cursor_pagination.py
    ├── integration/
    │   ├── __init__.py
    │   ├── conftest.py
    │   ├── test_insight_repository.py
    │   ├── test_recommendation_repository.py
    │   ├── test_run_repository.py
    │   ├── test_audit_repository.py
    │   ├── test_context_reader.py
    │   └── test_idempotency_replay.py
    ├── smoke/
    │   ├── __init__.py
    │   ├── conftest.py
    │   └── test_api_smoke.py
    └── e2e/
        ├── __init__.py
        └── test_investigation_e2e.py
```

---

## Implementation Steps (Ordered)

### Step 1 — Project Configuration
**Files:** `pyproject.toml`, `.gitignore`, `.dockerignore`, `.env.example`

- Replace minimal `pyproject.toml` with full project config
- **Python >=3.14**, key deps: `fastapi>=0.115`, `uvicorn[standard]>=0.30`, `pydantic>=2.10`, `pydantic-settings>=2.7`, `sqlalchemy>=2.0`, `asyncpg>=0.31`, `psycopg[binary]>=3.2`, `python-jose[cryptography]>=3.5.0`, `structlog>=24.1.0`, `opentelemetry-*>=1.39.1`, `prometheus-client>=0.21`, `httpx>=0.27`, `orjson>=3.10`, `tenacity>=8.2`
- Dev deps: `pytest>=8.3`, `pytest-asyncio>=0.24`, `pytest-cov>=5.0`, `factory-boy>=3.3.0`, `faker>=24.0.0`, `ruff>=0.8`
- pytest: `asyncio_mode = "auto"`, markers `unit`, `integration`, `smoke`, `e2e`
- Update `.env.example` with `SERVER_PORT=8003` and all feature flags

### Step 2 — Core Infrastructure
**Files:** `app/core/config.py`, `app/core/errors.py`, `app/core/database.py`, `app/core/logging.py`, `app/core/auth.py`, `app/core/dependencies.py`, `app/core/metrics.py`

**Config** (follow TM `app/core/config.py` pattern):
- Separate `BaseSettings` subclass per concern: `AppConfig` (env_prefix=`APP_`), `ServerConfig` (`SERVER_`), `DatabaseConfig` (`DATABASE_`), `Auth0Config` (`AUTH0_`), `SecurityConfig` (`SECURITY_`), `ObservabilityConfig` (`OTEL_`), `FeatureFlagsConfig` (`OPS_AGENT_`), `LLMConfig` (`LLM_`)
- `Settings` composes all, `@lru_cache` singleton via `get_settings()`
- Guardrail: `enforce_human_approval` must be `True` in non-local envs (model_validator)

**Errors**: `OpsAgentError` base with subclasses (`ValidationError`->400, `NotFoundError`->404, `ForbiddenError`->403, `ConflictError`->409, `DependencyError`->502, `InternalError`->500). Error codes from API contract: `OPS_AGENT_NOT_FOUND`, `OPS_AGENT_INVALID_REQUEST`, `OPS_AGENT_SCOPE_FORBIDDEN`, `OPS_AGENT_CONFLICT`, `OPS_AGENT_DEPENDENCY_FAILURE`, `OPS_AGENT_INTERNAL_ERROR`

**Database** (follow TM `app/core/database.py`): `create_async_engine()` + `async_sessionmaker`, `asyncpg` driver, `get_session()` generator with commit/rollback

**Auth** (adapt TM `app/core/auth.py`): Auth0 JWT with ops-agent scopes (`ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `ops_agent:draft`, `ops_agent:admin`), JWKS cache with circuit breaker, `require_scope()` dependency factory, local bypass with `SECURITY_SKIP_JWT_VALIDATION`

**Dependencies**: `Annotated` type aliases — `RequireOpsRead`, `RequireOpsRun`, `RequireOpsAck`, `RequireOpsDraft`, `RequireOpsAdmin`, `CurrentUser`

**Metrics**: Prometheus counters/histograms from observability doc — `ops_agent_investigation_requests_total`, `ops_agent_investigation_latency_seconds`, `ops_agent_recommendations_generated_total`, `ops_agent_recommendation_queue_open`, `ops_agent_rule_draft_exports_total`, `ops_agent_dependency_failures_total`

### Step 3 — Utilities
**Files:** `app/utils/uuid7.py`, `app/utils/idempotency.py`, `app/utils/clock.py`

- UUIDv7 generator (reuse from analytics-agent `app/utils/uuid7.py`)
- Idempotency key computation via SHA-256 for insights, recommendations, and rule drafts (keys from `docs/02-development/idempotency-and-replay.md`)
- `utc_now()` helper for testability

### Step 4 — Schemas (API DTOs)
**Files:** `app/schemas/v1/common.py`, `health.py`, `investigations.py`, `insights.py`, `recommendations.py`, `rule_drafts.py`

Versioned Pydantic V2 models matching the API contract in `docs/03-api/ops-agent-api-contract-v1.md`:
- Enums: `Severity`, `RunMode`, `RunStatus`, `RecommendationStatus`, `RecommendationType`, `ExportStatus`, `ModelMode`
- Request/Response pairs for each endpoint
- `ApiError` envelope, `PaginatedResponse` base with cursor support

### Step 5 — Persistence Layer
**Files:** `app/persistence/base.py`, `context_reader.py`, `run_repository.py`, `insight_repository.py`, `recommendation_repository.py`, `rule_draft_repository.py`, `audit_repository.py`

All use raw SQL via `sqlalchemy.text()`, return `dict[str, Any]` (TM pattern). No ORM models.

- **`context_reader.py`**: READ-ONLY against TM tables (`transactions`, `transaction_rule_matches`, `transaction_reviews`, `analyst_notes`, `transaction_cases`). Also card/merchant history queries for window stats.
- **`insight_repository.py`**: `upsert_insight()` with `ON CONFLICT` on idempotency_key, `add_evidence()`, `get_insights_for_transaction()`
- **`recommendation_repository.py`**: `upsert_recommendation()`, `list_open()` with keyset pagination on `(status, created_at DESC)`, `update_status()`
- **`audit_repository.py`**: Append-only `INSERT`, no UPDATE/DELETE
- **`base.py`**: `BaseCursor` for keyset pagination (base64-encoded composite cursor)

### Step 6 — Agent Core (Pure Logic)
**Files:** `app/agents/context_builder_core.py`, `pattern_engine_core.py`, `similarity_engine_core.py`, `recommendation_engine_core.py`

**Critical pattern**: These contain ZERO database access. Pure functions operating on in-memory data structures. This enables fast determinism tests.

- **`context_builder_core.py`**: `TransactionContext` and `WindowStats` frozen dataclasses, `compute_window_stats()`, `compute_all_windows()`, `extract_signals()`, `assemble_context()`
- **`pattern_engine_core.py`**: `PatternScore` frozen dataclass, `score_velocity_patterns()`, `score_decline_anomalies()`, `score_cross_merchant_patterns()`, `run_pattern_scoring()`, `compute_severity()`
- **`similarity_engine_core.py`**: `SimilarityMatch`/`SimilarityResult` frozen dataclasses, `freshness_weight()`, `evaluate_similarity()`
- **`recommendation_engine_core.py`**: `RecommendationCandidate` frozen dataclass, `generate_recommendations()` (policy rules), `compute_insight_severity()`

### Step 7 — Agent DB-Bound Modules + Pipeline
**Files:** `app/agents/context_builder.py`, `pattern_engine.py`, `similarity_engine.py`, `recommendation_engine.py`, `reasoning_engine.py`, `rule_draft_engine.py`, `audit_engine.py`, `pipeline.py`

Each DB-bound module reads from the DB, calls the corresponding `*_core.py` pure function, and writes results back.

- **`pipeline.py`**: Linear orchestrator with OpenTelemetry spans:
  1. `create_run` -> 2. `context_build` -> 3. `pattern_analysis` -> 4. `similarity_analysis` -> 5. `llm_reasoning` (stub) -> 6. `recommendation_generation` -> 7. `complete_run`
  - On failure: marks run as `FAILED` with error_summary
- **`reasoning_engine.py`**: Returns `None` (Phase 3 stub)
- **`rule_draft_engine.py`**: Raises `NotImplementedError` (Phase 2 stub)

### Step 8 — Services
**Files:** `app/services/investigation_service.py`, `insight_service.py`, `recommendation_service.py`, `rule_draft_service.py`, `audit_service.py`

- **`investigation_service.py`**: Validates feature flags, delegates to pipeline, enriches response with insight/evidence/recommendations
- **`recommendation_service.py`**: Worklist query with pagination, `acknowledge()` with status transition validation (only OPEN->ACKNOWLEDGED or OPEN->REJECTED), emits audit events
- **`rule_draft_service.py`**: Phase 1 stubs that create minimal records

### Step 9 — API Routes
**Files:** `app/api/routes/health.py`, `investigations.py`, `insights.py`, `recommendations.py`, `rule_drafts.py`

7 endpoints matching `docs/03-api/ops-agent-api-contract-v1.md`:
- All protected routes use `Annotated` auth dependencies from `core/dependencies.py`
- All use `response_model=` on decorators
- Base path: `/api/v1/ops-agent`
- Health routes at `/api/v1/health` (no ops-agent prefix)

### Step 10 — Application Entry Point
**File:** `app/main.py`

Follow TM `app/main.py` pattern:
- `create_app()` factory with `lifespan` context manager
- Store `settings`, `engine`, `session_factory` on `app.state`
- Register CORS middleware, all routers with `/api/v1` prefix
- Register exception handlers mapping `OpsAgentError` subclasses to HTTP codes
- Setup OTel tracing with FastAPIInstrumentor
- Disable `/docs` and `/redoc` in PROD
- Port 8003

### Step 11 — Database Migrations
**Files:** `db/migrations/001-004`, `db/ops_agent_schema.sql`

6 tables in `fraud_gov` as defined in `docs/02-development/domain-and-data-model.md`:
- `ops_agent_runs`, `ops_agent_insights`, `ops_agent_evidence`, `ops_agent_recommendations`, `ops_agent_rule_drafts`, `ops_agent_audit_log`
- Unique indexes on idempotency keys for replay safety
- Composite index `(status, created_at DESC)` on recommendations for worklist queries
- FK indexes for joins
- Grants: read/write on agent tables for `fraud_gov_app_user`, read-only for `fraud_gov_analytics_user`, SELECT on TM tables for `fraud_gov_app_user`
- Audit log: INSERT only (no UPDATE/DELETE grants)

### Step 12 — Dockerfile + Platform Integration
**Files:** `Dockerfile`, (external: `card-fraud-platform/docker-compose.apps.yml`)

- Multi-stage build: `python:3.14-slim` builder with `uv` -> slim runtime with `curl` + non-root `appuser`
- Port 8003, health check via `curl -f http://localhost:8003/api/v1/health`
- Platform compose: `ops-analyst-agent` service on `card-fraud-network`, depends on `postgres` + `transaction-management` healthy, profile `apps`

### Step 13 — Tests
**Files:** `tests/conftest.py`, all unit/integration/smoke/e2e test files

- **Root conftest**: env vars set before imports, mock token payloads with ops-agent scopes, `mock_session` fixture
- **Unit tests** (fast, no DB):
  - Core module determinism: call twice with identical input, assert equal output
  - Policy rule coverage for recommendation engine
  - Schema validation (accept/reject)
  - Auth scope enforcement
  - Idempotency key computation
  - Cursor pagination encoding/decoding
- **Integration tests** (real DB):
  - Repository CRUD operations
  - Idempotency replay (same key -> no duplicate)
  - Context reader against TM tables
- **Smoke tests** (TestClient):
  - Hit all 7 endpoints with mock auth, verify response shapes
- **E2E tests**:
  - Full flow: run investigation -> check recommendation queue -> acknowledge -> verify audit

---

## Key Design Decisions

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Port | 8003 | Next available (TM=8002, RM=8000, RE=8081) |
| DB driver | asyncpg (async) | Follow TM pattern; analytics-agent uses psycopg2 sync but TM is more mature |
| SQL approach | Raw `text()`, no ORM | Follow TM pattern; repositories return `dict[str,Any]` |
| Agent architecture | core/adapter split | Follow analytics-agent pattern; enables fast determinism tests |
| Pipeline orchestration | Simple async function with OTel spans | Phase 1 is linear; LangGraph reserved for Phase 3 when conditional branching needed |
| Idempotency | DB-level `ON CONFLICT` on unique indexes | Replay-safe without application locks |
| Auth | Scope-based via JWT permissions claim | Matches API contract; scopes are `ops_agent:read/run/ack/draft/admin` |
| Phase 2/3 stubs | `reasoning_engine` returns None, `rule_draft_engine` raises NotImplementedError | Preserves API contract surface while deferring implementation |
| Feature flags | `pydantic-settings` with `OPS_AGENT_` prefix | Consistent with platform conventions; no feature flag library needed |

---

## Verification Plan

1. **Unit tests**: `uv run pytest tests/unit -v` — all core modules pass determinism and policy tests
2. **Lint**: `uv run ruff check app/ tests/` — clean
3. **Local startup**: `uv run uvicorn app.main:create_app --factory --port 8003` — health endpoint returns 200
4. **Integration tests**: `uv run pytest tests/integration -v` (requires local DB) — all repository tests pass
5. **Smoke tests**: `uv run pytest tests/smoke -v` — all 7 API endpoints return expected shapes
6. **Docker build**: `docker build -t card-fraud-ops-analyst-agent .` — succeeds
7. **Platform stack**: Start from `card-fraud-platform` with `--profile apps` — ops-analyst-agent healthy
8. **Acceptance tests AT-001 through AT-008**: Run quick/deep investigation, acknowledge/reject, scope enforcement, idempotency replay

---

## Critical Reference Files

| Purpose | File |
|---------|------|
| App factory pattern | `card-fraud-transaction-management/app/main.py` |
| Config pattern | `card-fraud-transaction-management/app/core/config.py` |
| Auth pattern | `card-fraud-transaction-management/app/core/auth.py` |
| Database pattern | `card-fraud-transaction-management/app/core/database.py` |
| Repository pattern | `card-fraud-transaction-management/app/persistence/transaction_repository.py` |
| Core/adapter split | `card-fraud-analytics-agent/app/agents/context_core.py` |
| UUIDv7 | `card-fraud-analytics-agent/app/utils/uuid7.py` |
| Platform compose | `card-fraud-platform/docker-compose.apps.yml` |
| API contract | `docs/03-api/ops-agent-api-contract-v1.md` |
| Data model | `docs/02-development/domain-and-data-model.md` |
| Idempotency spec | `docs/02-development/idempotency-and-replay.md` |
| Acceptance matrix | `docs/04-testing/acceptance-test-matrix.md` |
