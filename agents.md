# agents.md — Ops Analyst Agent: Complete Reference

Authoritative single-file reference for running, configuring, testing, and debugging the
Card Fraud Ops Analyst Agent. Read this before touching any other doc.

---

## What This Agent Does

Autonomous fraud investigation pipeline. Given a transaction ID it:

1. Fetches transaction context and history from Transaction Management (TM)
2. Scores fraud patterns (velocity, decline ratio, amount anomalies, time/geo signals)
3. Finds similar historical transactions via vector embeddings (pgvector)
4. Synthesises a structured risk narrative via LLM reasoning (OpenAI)
5. Generates analyst-ready recommendations and optional rule draft packages

**Final fraud and rule activation decisions are always human-controlled.**
`OPS_AGENT_ENFORCE_HUMAN_APPROVAL=true` must never be disabled.

---

## LangGraph Pipeline — Tool Execution Order

```
planner_node  →  executor_node  →  planner_node  →  ...  →  completion_node
```

| Stage | Tool | LLM call? | What it does |
|-------|------|-----------|--------------|
| 1 | `planner_node` | ✅ OpenAI `/chat/completions` | Picks next tool (`tool`, `reason`, `confidence` JSON) |
| 2 | `context_tool` | ❌ | Fetches transaction + history from TM API |
| 3 | `pattern_tool` | ❌ | Local pattern scoring (velocity, decline ratio, amounts, hours) |
| 4 | `similarity_tool` | ❌ (embed only) | Embeds transaction → pgvector search for similar fraud cases |
| 5 | `link_analysis_tool` | ❌ | Local graph/neighbourhood analysis |
| 6 | `reasoning_tool` | ✅ OpenAI `/chat/completions` | Structured risk synthesis (narrative, hypotheses, confidence) |
| 7 | `recommendation_tool` | ❌ | Deterministic recommendation generation from all outputs |
| 8 | `rule_draft_tool` | ❌ | Rule draft package from recommendations + evidence |
| 9 | `completion_node` | ❌ | Final state assembly, severity/confidence, persistence |

LLM is called **only in stages 1 and 6**. Everything else is deterministic.
Each investigation makes **2 OpenAI API calls**: 1 embedding (similarity_tool) + 1 chat completion (reasoning_tool).

---

## Doppler Config (local)

All secrets live in Doppler project `card-fraud-ops-analyst-agent`, config `local`.
Never use `.env` files. Restart the server/container after any secret change.

### Current local config (verified working)

| Key | Value | Notes |
|-----|-------|-------|
| `LLM_PROVIDER` | `openai/gpt-5-mini` | Format: `provider/model-name` |
| `LLM_BASE_URL` | `https://api.openai.com/v1` | OpenAI API endpoint |
| `LLM_TIMEOUT` | `30` | OpenAI responds in <2s |
| `LLM_MAX_COMPLETION_TOKENS` | `512` | Sufficient for JSON responses |
| `LLM_CONSISTENCY_THRESHOLD` | `0.3` | |
| `LLM_API_KEY` | *(set in Doppler)* | OpenAI API key — required |
| `PLANNER_MODEL_NAME` | `openai/gpt-5-mini` | **Must match `LLM_PROVIDER` exactly** |
| `VECTOR_ENABLED` | `true` | |
| `VECTOR_API_BASE` | `https://api.openai.com/v1` | OpenAI embeddings endpoint |
| `VECTOR_MODEL_NAME` | `text-embedding-3-large` | 1024-dim output via `dimensions` param |
| `VECTOR_DIMENSION` | `1024` | Matches pgvector schema |
| `OPS_AGENT_ENABLE_LLM_REASONING` | `true` | Enables reasoning_tool LLM call |
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | `true` | Never disable |
| `SECURITY_SKIP_JWT_VALIDATION` | `true` | Local/test only |

### Only one API key needed

**`LLM_API_KEY` is the single key for both LLM and embeddings.**
The embedding client inherits it automatically for any non-localhost `VECTOR_API_BASE`.

---

## Doppler: Two Projects, One Source of Truth Each

| Doppler project | Owns | Used by |
|----------------|------|---------|
| `card-fraud-ops-analyst-agent` | LLM, planner, vector, reasoning flags | `uv run` on host + Docker container (via merge) |
| `card-fraud-platform` | DB, auth, S3, CORS, OTEL | All containers via docker-compose |

LLM secrets are **not** duplicated in `card-fraud-platform`. Both projects are merged at container start so docker-compose `${LLM_PROVIDER}` etc. resolve from the ops-agent project.

---

## Platform Services — Startup Order

All services run via Docker Compose in the `card-fraud-platform` sibling repo.

```bash
cd ../card-fraud-platform

# 1. Start shared infra (Postgres, Redis, Jaeger, MinIO, Redpanda)
doppler run --project card-fraud-platform --config local -- docker compose up -d

# 2. Build + start app services — merge both Doppler projects
eval $(doppler secrets download --project card-fraud-ops-analyst-agent --config local \
  --no-file --format env-no-quotes) && \
  doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d --build transaction-management ops-analyst-agent

# 3. Verify all services are healthy
curl http://localhost:8002/api/v1/health     # Transaction Management
curl http://localhost:8003/api/v1/health     # Ops Analyst Agent
```

### Rebuilding after code changes

After any change to `app/**/*.py`, `Dockerfile`, `pyproject.toml`, or `uv.lock`:

```bash
cd ../card-fraud-platform
eval $(doppler secrets download --project card-fraud-ops-analyst-agent --config local \
  --no-file --format env-no-quotes) && \
  doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d --build ops-analyst-agent
```

---

## Development (no Docker — hot reload)

```bash
cd card-fraud-ops-analyst-agent

uv sync --extra dev                  # Install all deps
uv run db-init                       # Create ops_agent_* tables (first time only)
uv run doppler-local                 # Start dev server on :8003 with Doppler secrets
```

---

## Running Tests

### Quality gates (always run before commit)

```bash
uv run ruff check app/ tests/ cli/ scripts/          # Lint — 0 errors required
uv run ruff format --check app/ tests/ cli/ scripts/ # Format check
uv run pytest tests/unit -v                           # Unit tests, no external deps
uv run pytest tests/smoke -v                          # Smoke tests via TestClient
```

### Integration (requires live Postgres)

```bash
doppler run --config local -- uv run pytest tests/integration -v
```

---

## E2E Test Matrix — 31 Scenarios

### Prerequisites

1. All platform services running (see above)
2. Container is fresh (rebuilt after any source change)
3. `LLM_API_KEY` set in Doppler (OpenAI key)
4. Test scenarios seeded into the database

```bash
# Seed all 16 fraud scenarios + generate the manifest (idempotent, safe to re-run)
cd card-fraud-ops-analyst-agent
doppler run --config local -- uv run python scripts/seed_test_scenarios.py
```

Seeding creates `htmlcov/e2e-seed-manifest.json` mapping each scenario name to its
transaction ID. The E2E runner reads this file — **do not delete it between runs**.

### Step 1 — Run a single case first (preflight validation)

```bash
doppler run --config local -- uv run pytest \
  tests/e2e/test_scenarios.py::test_llm_chat_preflight \
  -v --tb=short
```

This validates OpenAI API reachability and a live chat completion call — before spending time on the full matrix.

### Step 2 — Run one scenario end-to-end

```bash
doppler run --config local -- uv run pytest \
  "tests/e2e/test_scenarios.py::test_scenario_likely_fraud" \
  -v --tb=short -s
```

### Step 3 — Full 31-scenario matrix

```bash
# Standard pytest run (all e2e markers)
doppler run --config local -- uv run pytest tests/e2e/test_scenarios.py \
  -v --tb=short -s \
  --html=htmlcov/e2e-pytest-report.html --self-contained-html

# OR use the dedicated matrix runner (richer KPI output)
doppler run --config local -- uv run python scripts/run_e2e_matrix_detailed.py
```

### 24 pytest tests vs 31 matrix rows

- `uv run pytest tests/e2e/test_scenarios.py` currently collects **24 pytest tests**.
- `uv run python scripts/run_e2e_matrix_detailed.py` executes **31 matrix rows** from the seed manifest and scenario buckets.
- They overlap but are not identical harnesses:
- Pytest suite includes explicit preflight tests, KPI gate assertion, and acknowledge-flow test contracts.
- Matrix runner executes scenario rows with richer audit/KPI reporting and its own provider/readiness prechecks.

### E2E scenario list (16 fraud scenarios + preflights + pipeline tests)

| Category | Test | Expected |
|----------|------|----------|
| Preflight | `test_llm_chat_preflight` | OpenAI API reachable + chat completion succeeds |
| Preflight | `test_vector_embedding_preflight` | Embedding endpoint + 1024-dim response |
| Preflight | `test_seed_manifest_preflight` | All 16 scenarios in manifest |
| Fraud | `CARD_TESTING_PATTERN` | MEDIUM+ severity, ≥2 recommendations |
| Fraud | `VELOCITY_BURST` | HIGH+ severity, ≥2 recommendations |
| Fraud | `CROSS_MERCHANT_SPREAD` | MEDIUM+ severity, ≥1 recommendation |
| Fraud | `HIGH_DECLINE_RATIO` | MEDIUM+ severity, ≥2 recommendations |
| Fraud | `LIKELY_FRAUD` | LOW+ severity, ≥1 recommendation |
| Fraud | `APPROVED_LIKELY_FRAUD` | LOW+ severity, ≥1 recommendation |
| Fraud | `AMOUNT_ROUND_NUMBER` | LOW+ severity, ≥1 recommendation |
| Fraud | `AMOUNT_HIGH` | LOW+ severity, ≥1 recommendation |
| Fraud | `TIME_UNUSUAL_HOUR` | LOW+ severity, ≥1 recommendation |
| Fraud | `TIMEZONE_MISMATCH` | LOW+ severity, ≥1 recommendation |
| Fraud | `CARD_TESTING_SEQUENCE` | MEDIUM+ severity, ≥1 recommendation |
| Legitimate | `LEGITIMATE` | LOW severity, 0 recommendations |
| Legitimate | `LEGITIMATE_WITH_COUNTER_EVIDENCE` | LOW severity, 0 recommendations |
| Edge | `EDGE_FIRST_TRANSACTION` | LOW severity (limited history) |
| Edge | `EDGE_MISSING_DATA` | LOW severity (graceful null handling) |
| Extended | `COUNTER_EVIDENCE_EXTENDED` | LOW severity, downgraded by counter-evidence |
| KPI Gate | `test_acceptance_kpi_gate` | scenario_pass_rate=1.0, fraud_recall≥0.80 |
| Agentic | `test_llm_agentic_mode` | `model_mode == "agentic"` |
| Pipeline | `test_end_to_end_acknowledge_flow` | Full investigate → acknowledge flow |

### Acceptance KPI thresholds

| KPI | Target | What it measures |
|-----|--------|-----------------|
| `scenario_pass_rate` | 1.0 (100%) | All scenarios must pass |
| `fraud_recall_medium_plus` | ≥ 0.80 | High-confidence fraud scenarios at MEDIUM+ severity |
| `low_risk_precision_low_only` | 1.0 | Legitimate scenarios must not be over-escalated |
| `recommendation_coverage` | 1.0 | Scenarios requiring recs must produce them |
| `run_investigation_p95_ms` | ≤ 130,000 ms | p95 run latency |
| `detail_fetch_p95_ms` | ≤ 4,000 ms | p95 detail GET latency |

### E2E retry behaviour

Scenarios retry up to `E2E_SCENARIO_MAX_ATTEMPTS` times (default: 5) on transient
LLM failures (empty content, timeout, JSON parse error). Set to 1 for fast CI failure:

```bash
E2E_SCENARIO_MAX_ATTEMPTS=1 doppler run --config local -- uv run pytest tests/e2e/test_scenarios.py -v
```

---

## Agentic E2E (LangGraph pipeline tests)

```bash
doppler run --config local -- uv run pytest tests/e2e/test_agentic_e2e.py -v --tb=short
```

Covers: health check, full agentic run, investigation detail, insights,
worklist, tool execution persistence, resume of non-existent investigation, rule-draft 404.

---

## Observability

| UI | URL | What to look at |
|----|-----|-----------------|
| Jaeger | http://localhost:16686 | Per-stage pipeline traces, LLM latency |
| Grafana | http://localhost:3000 | Tool latency dashboards (admin/admin) |
| Prometheus | http://localhost:9090 | Raw `llm_request_*`, `tool_execution_*` metrics |
| API health | http://localhost:8003/api/v1/health/ready | Feature flag state, dependency status |

---

## Troubleshooting

### `RuntimeError: Ops-agent container is older than local source files`

Source files changed after the last Docker build. Rebuild:
```bash
cd ../card-fraud-platform
eval $(doppler secrets download --project card-fraud-ops-analyst-agent --config local \
  --no-file --format env-no-quotes) && \
  doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d --build ops-analyst-agent
```

### `RuntimeError: No Docker container is publishing local port 8003`

The ops-analyst-agent container is not running. Start it:
```bash
cd ../card-fraud-platform
eval $(doppler secrets download --project card-fraud-ops-analyst-agent --config local \
  --no-file --format env-no-quotes) && \
  doppler run --project card-fraud-platform --config local -- \
  docker compose -f docker-compose.yml -f docker-compose.apps.yml \
  --profile platform up -d transaction-management ops-analyst-agent
```

### `test_llm_chat_preflight` fails — API key or model issue

Check `LLM_API_KEY` is set in Doppler and the model name is correct:
```bash
doppler secrets get LLM_API_KEY LLM_PROVIDER
```

### `test_seed_manifest_preflight` fails — manifest missing

Re-run the seed script:
```bash
doppler run --config local -- uv run python scripts/seed_test_scenarios.py
cat htmlcov/e2e-seed-manifest.json   # should list all 16 scenario keys
```

### `reasoning_llm_pass=False` — LLM returned invalid JSON

OpenAI occasionally returns malformed JSON under load. Options:
- Increase `LLM_MAX_COMPLETION_TOKENS` to `768` in Doppler
- The test runner retries up to 5 times automatically

### `PLANNER_MODEL_NAME must match LLM_PROVIDER`

Both Doppler keys must be identical:
```bash
doppler secrets set LLM_PROVIDER=openai/gpt-5-mini
doppler secrets set PLANNER_MODEL_NAME=openai/gpt-5-mini
```

### Settings not taking effect after Doppler change

Config is cached at startup via `@lru_cache`. Restart the server or rebuild the container.

---

## Key Code Locations

| Concern | Location |
|---------|----------|
| LLM adapter (OpenAI `/chat/completions`) | `app/llm/provider.py` — `LLMChatProvider` |
| LangGraph graph definition | `app/agent/graph.py` |
| Planner (LLM tool selection) | `app/agent/planner.py` |
| All tool implementations | `app/tools/` |
| Config + feature flags | `app/core/config.py` |
| Docker guard (stale container check) | `scripts/docker_guard.py` |
| E2E scenario matrix | `tests/e2e/test_scenarios.py` |
| Agentic pipeline E2E | `tests/e2e/test_agentic_e2e.py` |
| Seed script (test data) | `scripts/seed_test_scenarios.py` |
| Matrix runner (detailed KPI output) | `scripts/run_e2e_matrix_detailed.py` |

---

## Human Decision Boundary

The agent is an intelligence platform, not an autonomous adjudicator.

```
Agent produces:        Human decides:
─────────────          ──────────────
Risk insight     →     Accept / reject recommendation
Recommendation   →     Acknowledge / escalate / dismiss
Rule draft       →     Approve / modify / reject in Rule Management
```

`OPS_AGENT_ENFORCE_HUMAN_APPROVAL=true` is enforced at startup in all environments.
Setting it to `false` in production raises a `RuntimeError` and prevents the server from starting.
