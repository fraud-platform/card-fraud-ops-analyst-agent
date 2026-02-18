# Code Map - Card Fraud Ops Analyst Agent

Architecture overview, module responsibilities, data flow, and key patterns.

## Project Structure Overview

```
card-fraud-ops-analyst-agent/
├── app/                          # FastAPI application
│   ├── api/routes/               # API endpoint handlers
│   ├── agents/                   # Pipeline stages (core + adapters)
│   ├── clients/                  # External HTTP clients
│   ├── core/                     # Config, auth, database, logging
│   ├── llm/                      # LLM provider and prompts
│   ├── persistence/               # Database repositories
│   ├── schemas/v1/               # Pydantic request/response models
│   ├── services/                 # Business logic orchestration
│   ├── utils/                    # Helper utilities
│   └── main.py                   # FastAPI app factory
├── cli/                          # uv run entry point scripts
├── scripts/                      # Database setup and utilities
├── tests/                        # Unit, integration, smoke, e2e tests
├── db/migrations/                 # SQL migration files
├── docs/                         # Architecture and API docs
├── memory/                       # Session learnings
├── CLAUDE.md                     # Points to AGENTS.md
├── AGENTS.md                     # Canonical agent instructions
├── README.md                     # Project overview and quick start
└── pyproject.toml                # Dependencies, tooling, scripts
```

## Architecture Layers

### 1. API Layer (`app/api/routes/`)

**Entry Points** - HTTP request handling

| Route File | Endpoints | Auth Scopes |
|-----------|-----------|-------------|
| `health.py` | GET `/api/v1/health` | none |
| `investigations.py` | POST `/api/v1/ops-agent/investigations/run`<br>GET `/api/v1/ops-agent/investigations/{run_id}` | `ops_agent:run`<br>`ops_agent:read` |
| `insights.py` | GET `/api/v1/ops-agent/transactions/{txn_id}/insights` | `ops_agent:read` |
| `recommendations.py` | GET `/api/v1/ops-agent/worklist/recommendations`<br>POST `/api/v1/ops-agent/worklist/recommendations/{id}/acknowledge` | `ops_agent:read`<br>`ops_agent:ack` |
| `rule_drafts.py` | POST `/api/v1/ops-agent/rule-drafts`<br>POST `/api/v1/ops-agent/rule-drafts/{id}/export` | `ops_agent:draft` |

**Patterns:**
- Use `Annotated[AuthenticatedUser, Depends(require_scope("scope"))]` for auth
- Pydantic schemas for request/response validation
- Services layer for business logic (no business logic in routes)
- HTTP status codes: 200, 201, 404, 400, 403, 409, 500, 502

### 2. Services Layer (`app/services/`)

**Orchestration** - Business logic coordination

| Service | Responsibility | Key Methods |
|---------|---------------|-------------|
| `investigation_service.py` | Orchestrates investigation pipeline | `run_investigation()`, `get_investigation()` |
| `insight_service.py` | Query insight snapshots | `get_insights_for_transaction()` |
| `recommendation_service.py` | Worklist management and status transitions | `list_worklist()`, `acknowledge()` (uses `audit_repository` directly for audit events) |
| `rule_draft_service.py` | Rule draft creation and export | `create_draft()`, `export_draft()` (uses `audit_repository` directly for audit events) |

**Patterns:**
- Async methods throughout
- Repository calls for persistence (including `audit_repository` used directly)
- Agent engines for processing
- Raise `OpsAgentError` hierarchy for errors
- Return Pydantic models to routes

### 3. Agent Layer (`app/agents/`)

**Pipeline Stages** - Core logic + DB adapters

**Core/Adapter Split:**

| Core File (Pure Logic) | Adapter File (DB-Bound) | Responsibility |
|------------------------|------------------------|----------------|
| `context_builder_core.py` | `context_builder.py` | Feature extraction from transaction data |
| `pattern_engine_core.py` | `pattern_engine.py` | Anomaly detection and scoring |
| `similarity_engine_core.py` | `similarity_engine.py` | Similarity threshold evaluation |
| `recommendation_engine_core.py` | `recommendation_engine.py` | Policy-based recommendation generation |
| `reasoning_core.py` | `reasoning_engine.py` | LLM-based narrative reasoning |
| `rule_draft_core.py` | `rule_draft_engine.py` | Rule draft package generation |
| — | `pipeline.py` | Orchestrates all stages in sequence |

**Core Module Pattern:**
- Pure functions (no DB access)
- Deterministic logic (fully testable)
- Dataclasses for data structures
- Fast unit tests (no mocks needed)

**Adapter Module Pattern:**
- DB reads via repositories
- Call core functions for logic
- Write results back via repositories
- OpenTelemetry spans for observability

### 4. Persistence Layer (`app/persistence/`)

**Data Access** - Async SQL with asyncpg

| Repository | Tables | Operations |
|------------|--------|------------|
| `run_repository.py` | `ops_agent_runs` | CRUD, idempotency check |
| `insight_repository.py` | `ops_agent_insights`, `ops_agent_evidence` | CRUD with evidence nesting |
| `recommendation_repository.py` | `ops_agent_recommendations` | CRUD, acknowledge, pagination |
| `rule_draft_repository.py` | `ops_agent_rule_drafts` | CRUD, export tracking |
| `audit_repository.py` | `ops_agent_audit_log` | Append-only writes |
| `context_reader.py` | `fraud_gov.*` (TM tables) | READ-ONLY queries |
| `base.py` | — | `row_to_dict()` helper, `BaseCursor` pagination |

**Patterns:**
- `sqlalchemy.text()` for raw SQL
- `asyncpg` driver (async)
- Return `dict[str, Any]` (not ORM models)
- `row_to_dict(row)` converts UUID→str
- JSONB columns: use `json.dumps(dict)` not raw dict
- Transaction management via database engine

### 5. LLM Layer (`app/llm/`)

**Language Model Integration** - LiteLLM provider

| Module | Responsibility |
|--------|---------------|
| `provider.py` | LiteLLM client, API base/key handling |
| `redaction.py` | PII redaction before LLM calls |
| `consistency.py` | Output validation and sanitization |
| `prompts/templates.py` | Prompt template loader |
| `prompts/investigation_v1.py` | Investigation reasoning prompt |

**Patterns:**
- Single LLM config source: `LLMConfig.provider`
- Graceful fallback to deterministic on LLM failure
- Redaction of PII before sending to LLM
- Output validation with error recovery

### 6. Core Infrastructure (`app/core/`)

**Cross-Cutting Concerns**

| Module | Responsibility |
|--------|---------------|
| `config.py` | Pydantic settings per concern (app, database, auth, llm, feature_flags) |
| `auth.py` | Auth0 JWT validation, `require_scope()` dependency factory |
| `database.py` | Async SQLAlchemy engine, session lifecycle |
| `dependencies.py` | Annotated type aliases for FastAPI dependencies |
| `errors.py` | `OpsAgentError` hierarchy (validation, not found, forbidden, conflict, dependency, internal) |
| `logging.py` | Structlog configuration (JSON for prod, console for local) |
| `metrics.py` | Prometheus counters and histograms |

### 7. Schemas Layer (`app/schemas/v1/`)

**Data Transfer Objects** - Pydantic V2

| Schema File | Models |
|-------------|--------|
| `common.py` | Enums, `ApiError`, `PaginatedResponse` |
| `health.py` | `HealthResponse`, `ReadyResponse` |
| `investigations.py` | `RunInvestigationRequest`, `InvestigationResponse` |
| `insights.py` | `InsightResponse`, `EvidenceItem` |
| `recommendations.py` | `RecommendationResponse`, `AcknowledgementRequest` |
| `rule_drafts.py` | `RuleDraftResponse`, `ExportResponse` |

**Patterns:**
- Frozen dataclasses where appropriate
- Strict validation (`model_config = {"extra": " forbid"}`)
- Field aliases for API/DB mismatches (e.g., `recommendation_type AS type`)
- Default values for computed fields (e.g., `priority: int = 0`)

## Data Flow: Investigation Pipeline

```
1. POST /investigations/run
   ↓
2. investigations.py (route handler)
   - Validates request (Pydantic)
   - Calls investigation_service.run_investigation()
   ↓
3. investigation_service.py
   - Creates run record (run_repository)
   - Calls pipeline.run_investigation_pipeline()
   ↓
4. pipeline.py (orchestrator with OTel spans)
   Stage 1: context_builder.py
     - Reads TM data (context_reader)
     - Calls context_builder_core.build_transaction_context()
     - Stores in run.context_payload

   Stage 2: pattern_engine.py
     - Calls pattern_engine_core.score_anomalies()
     - Detects velocity anomalies, amount outliers, geo anomalies
     - Returns list of EvidenceItem

   Stage 3: similarity_engine.py
     - SQL overlap query (context_reader)
     - Calls similarity_engine_core.evaluate_similarity()
     - Returns list of EvidenceItem

   Stage 4: reasoning_engine.py
     - If LLM enabled: calls LLM with investigation prompt
     - If LLM disabled or fails: returns None (graceful fallback)
     - Returns narrative reasoning text

   Stage 5: recommendation_engine.py
     - Calls recommendation_engine_core.generate_recommendations()
     - Applies policy rules (velocity, amount, similarity, geo, pattern)
     - Returns list of RecommendationCandidate

   Stage 6: rule_draft_engine.py
     - Calls rule_draft_core.build_rule_draft_packages()
     - Generates rule conditions from evidence
     - Returns list of RuleDraftPackage
   ↓
5. investigation_service.py (cont.)
   - Persists insights (insight_repository)
   - Persists recommendations (recommendation_repository)
   - Persists rule drafts (rule_draft_repository)
   - Updates run status to "completed"
   ↓
6. investigations.py (route handler)
   - Returns InvestigationResponse
   - 200 OK with run_id, insights, recommendations
```

## Database Schema

### This Project's Tables (`ops_agent_*`)

```sql
ops_agent_runs
  - id (PK, UUID)
  - transaction_id (FK → fraud_gov.transactions.id)
  - trigger_ref (unique, idempotency key)
  - status (enum: pending, in_progress, completed, failed)
  - context_payload (JSONB)
  - reasoning_output (text)
  - created_at, updated_at

ops_agent_insights
  - id (PK, UUID)
  - run_id (FK → ops_agent_runs.id)
  - transaction_id (FK → fraud_gov.transactions.id)
  - insight_summary (text)
  - anomaly_score (numeric)
  - created_at

ops_agent_evidence
  - id (PK, UUID)
  - insight_id (FK → ops_agent_insights.id)
  - evidence_type (enum)
  - evidence_payload (JSONB)
  - created_at

ops_agent_recommendations
  - id (PK, UUID)
  - run_id (FK → ops_agent_runs.id)
  - transaction_id (FK → fraud_gov.transactions.id)
  - recommendation_type (enum)
  - recommendation_payload (JSONB)
  - status (enum: pending, acknowledged, dismissed, expired)
  - acknowledged_at
  - expires_at
  - created_at

ops_agent_rule_drafts
  - id (PK, UUID)
  - insight_id (FK → ops_agent_insights.id)
  - rule_name
  - rule_condition (JSONB)
  - rule_action (enum)
  - rule_description
  - draft_metadata (JSONB)
  - export_status (enum: not_exported, exported, failed)
  - exported_at
  - created_at

ops_agent_audit_log
  - id (PK, UUID)
  - event_type
  - event_category
  - actor_id
  - resource_type
  - resource_id
  - action
  - event_metadata (JSONB)
  - created_at
```

### Read-Only Tables (from Transaction Management)

```sql
fraud_gov.transactions                    -- Source transaction data
fraud_gov.transaction_rule_matches        -- Rule evaluation results
fraud_gov.transaction_reviews            -- Analyst reviews
fraud_gov.analyst_notes                  -- Analyst notes
fraud_gov.transaction_cases              -- Case management
```

## Key Conventions

### Naming Conventions
- **Files**: `snake_case.py` (e.g., `context_builder.py`)
- **Docs**: `kebab-case.md` (e.g., `local-setup.md`)
- **Exceptions**: `README.md`, `CLAUDE.md`, `AGENTS.md`, `DEVELOPER_GUIDE.md`, `CODEMAP.md`
- **Classes**: `PascalCase` (e.g., `InvestigationService`)
- **Functions/variables**: `snake_case` (e.g., `run_investigation`)
- **Constants**: `UPPER_SNAKE_CASE` (e.g., `MAX_RETRIES`)
- **API paths**: `/kebab-case/` (e.g., `/rule-drafts`)

### Core/Adapter Naming
- **Core files**: `{module}_core.py` (pure logic, no DB)
- **Adapter files**: `{module}.py` (DB-bound, calls core)
- **Example**: `context_builder_core.py` + `context_builder.py`

### Error Handling
- Use `OpsAgentError` hierarchy from `app/core/errors.py`
- Routes: let exceptions propagate, error handler converts to HTTP status
- Services: raise specific error types
- Repositories: raise `InternalError` on DB failures

### Async Patterns
- All DB calls are async (asyncpg)
- All service methods are async
- Routes use `async def`
- Use `await` for all DB operations

### UUID Handling
- Use `uuid.uuid7()` for ID generation (Python 3.14+)
- Always convert UUID to string at persistence boundary: `str(uuid_val)`
- Use `row_to_dict(row)` helper for consistency

### JSONB Handling
- Always use `json.dumps(dict)` when inserting JSONB
- asyncpg returns JSONB as dict (no parsing needed)
- Evidence nested under `evidence_payload` key

## Entry Points

### uv run CLI Commands

```bash
# Development
uv run doppler-local           # Start dev server with Doppler secrets
uv run doppler-local-test      # Run tests with local DB

# Database
uv run db-init                 # Create tables (local)
uv run db-reset-tables         # Drop/recreate tables
uv run db-verify               # Verify tables exist
uv run db-load-test-data       # Load seed data

# Testing
uv run test                    # Unit tests
uv run test-smoke              # Smoke tests
uv run test-all                # All tests

# Code Quality
uv run lint                    # Ruff check
uv run format                  # Ruff format

# Auth0
uv run auth0-bootstrap         # Bootstrap Auth0 API + M2M
uv run auth0-verify            # Verify Auth0 config

# E2E
uv run e2e-local              # Local end-to-end test
```

### API Endpoints

Base URL: `http://localhost:8003`

- Health: `GET /api/v1/health`
- OpenAPI docs: `GET /docs`
- All ops-agent routes: `/api/v1/ops-agent/...`

## Important Patterns

### 1. Core/Adapter Separation
- `*_core.py`: Pure functions, no DB, fast unit tests
- `*.py`: DB-bound adapter, calls core, persists results

### 2. Repository Pattern
- All DB access through repositories
- No raw SQL in services or agents
- Return `dict[str, Any]` not ORM models

### 3. Service Orchestration
- Services coordinate repositories + agents
- No business logic in routes
- Raise domain-specific errors

### 4. Idempotency
- `trigger_ref` unique constraint on runs table
- Check before insert: `get_run_by_trigger_ref()`
- Enables safe retry of failed investigations

### 5. Graceful Degradation
- LLM failures fallback to deterministic
- JSON parse errors logged but don't fail pipeline
- Partial success supported (e.g., some recommendations fail)

### 6. Audit Trail
- Every action logged to `ops_agent_audit_log`
- Append-only (no updates/deletes)
- Supports compliance and debugging

### 7. Pagination
- Keyset pagination via `BaseCursor`
- Use `created_at` + `id` for ordering
- No offset-based pagination (slow at scale)

## Testing Strategy

### Unit Tests (`tests/unit/`)
- Fast (no DB, no external deps)
- Mock all external calls
- Test core logic in isolation
- 140 tests total

### Smoke Tests (`tests/smoke/`)
- FastAPI TestClient
- Test endpoint contracts
- No real DB needed
- 10 tests total

### Integration Tests (`tests/integration/`)
- Requires running Postgres
- Test repository queries
- Test pipeline stages
- Skipped when DB not available

### E2E Tests (`tests/e2e/`)
- Full stack with real DB
- Test complete flows
- `scripts/e2e_local_test.py`
- CLI: `uv run e2e-local`

## Monitoring

### OpenTelemetry Spans
Pipeline stages emit spans:
- `ops_agent.pipeline` - Parent span for entire pipeline
- `ops_agent.context_build` - Context building stage
- `ops_agent.pattern_analysis` - Pattern analysis stage
- `ops_agent.similarity_analysis` - Similarity analysis stage
- `ops_agent.llm_reasoning` - LLM reasoning stage
- `ops_agent.recommendations` - Recommendation generation stage

### Prometheus Metrics
Counters:
- `investigation_runs_total{status}`
- `recommendations_created_total{type}`
- `recommendations_acknowledged_total`

Histograms:
- `investigation_duration_seconds{stage}`
- `database_query_duration_seconds{table,operation}`

### Logging
- Structured JSON logs (prod)
- Console logs (local)
- Correlation IDs: `run_id`, `transaction_id`
- Log levels: DEBUG, INFO, WARNING, ERROR

## Configuration

### Feature Flags
- `OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT` (default: false)
- `OPS_AGENT_ENABLE_LLM_REASONING` (default: false)

### Security Settings
- `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` (must be true in prod)
- `SECURITY_SKIP_JWT_VALIDATION` (local dev only)

### LLM Settings
- `LLM_PROVIDER` (e.g., "anthropic", "openai", "ollama/phi3")
- `LLM_API_KEY`
- `LLM_API_BASE`
- `LLM_FALLBACK_MODEL` (for deterministic mode)

### Database Settings
- `DATABASE_URL_APP` (app user, read/write)
- `DATABASE_URL_READONLY` (read-only replica)
- `DATABASE_URL_ADMIN` (DDL only, for migrations)

## Related Files

- `AGENTS.md` - Canonical agent instructions
- `CLAUDE.md` - Quick reference
- `README.md` - Project overview
- `DEVELOPER_GUIDE.md` - Setup and workflow
- `memory/MEMORY.md` - Session learnings
- `docs/` - Detailed architecture docs
