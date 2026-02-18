# Implementation Roadmap

## Status Summary (2026-02-15)

| Phase | Status | Quality Gates |
|-------|--------|--------------|
| Phase 1 — Foundation & Deterministic Core | ✅ COMPLETE | Lint/format clean; core test suites passing |
| Phase 2 — Analyst Actions & Rule Draft Handoff | ✅ COMPLETE | Lint/format clean; core test suites passing |
| Phase 3 — LLM-Hybrid Enablement | ✅ COMPLETE | Lint/format clean; core test suites passing |
| Integration — Platform + E2E wiring | ✅ COMPLETE | — |
| Monitoring — OTel spans + Prometheus + Jaeger | ✅ COMPLETE | Lint/format clean; core test suites passing |
| Live E2E Testing — Real DB with actual TM data | ✅ COMPLETE | Pipeline runs; response mapping fixed |
| Phase 4 — Advanced Analytics (docs/archive/08-improvements) | ✅ COMPLETE | Advanced analytics modules and tests integrated |

See `docs/archive/phase-2-3-implementation-plan.md` for detailed step-by-step status.
See `docs/archive/08-improvements/fraud-analytics-improvements-plan.md` for Phase 4 detail.

### Phase 4 Deliverables (2026-02-15)
- **Vector Similarity Search**: `ops_agent_transaction_embeddings` table with pgvector 0.8.1, IVFFlat index
- **Counter-Evidence Detection**: 3DS success + trusted device signals in `similarity_engine_core.py`
- **Conflict Matrix Analysis**: `conflict_matrix.py` — multi-dim evidence correlation, feature-flagged in pipeline
- **Enhanced Narrative (v2 Prompt)**: `investigation_v2.py` — domain-aware, counter-evidence aware; activated by `OPS_AGENT_NARRATIVE_VERSION=v2`
- **Explanation Builder**: `explanation_builder.py` — structured markdown investigation reports, feature-flagged
- **Freshness Weighting**: `freshness.py` — exponential decay per evidence type, applied in `evidence_builder.py`
- **Structured Evidence Envelope**: `evidence_builder.py` + migration 007 adds `category`, `strength`, `freshness_weight`, `related_transaction_ids`, `evidence_references` columns to `ops_agent_evidence`
- **New Feature Flags**: `OPS_AGENT_CONFLICT_MATRIX_ENABLED`, `OPS_AGENT_EXPLANATION_BUILDER_ENABLED`, `OPS_AGENT_NARRATIVE_VERSION`, `VECTOR_ENABLED` (`VECTOR_ENABLED` now default-on; others remain opt-in)
- **OllamaProvider**: Native Ollama HTTP client (no litellm dependency for local/cloud Ollama)

### Monitoring Architecture
- **Jaeger All-in-One** added to `docker-compose.yml` (ports 16686 UI, 4317 OTLP gRPC, 4318 OTLP HTTP)
- **OTel spans**: `ops_agent.pipeline` parent + child span per stage (context_build, pattern_analysis, similarity_analysis, llm_reasoning, recommendations)
- **Prometheus metrics**: `ops_agent_investigation_*`, `ops_agent_pipeline_stage_latency_seconds`, `ops_agent_llm_*`, `ops_agent_recommendations_generated_total`
- **API response**: `duration_ms` + `stage_durations` dict now returned in `RunResponse`/`DetailResponse`; optionally includes `conflict_matrix` and `explanation` when feature flags enabled
- **Fraud-relevant span attributes**: `pattern.severity`, `similarity.score`, `run.model_mode`, `llm.confidence`, `conflict.score`

---

## Goal

Deliver a production-grade `card-fraud-ops-analyst-agent` integrated with the Card Fraud Platform, with human final authority and auditable autonomous assistance.

## Phase 1 - Foundation and Deterministic Core ✅ COMPLETE

### Objectives

- Stand up Ops Agent service skeleton and contracts.
- Implement deterministic evidence pipeline first.
- Establish data model, permissions, and observability baseline.

### Deliverables by Repository

#### `card-fraud-ops-analyst-agent`

- Implement service skeleton with health/readiness endpoints.
- Implement v1 API surfaces from `docs/03-api/ops-agent-api-contract-v1.md`.
- Implement deterministic modules:
  - context builder
  - pattern engine
  - similarity engine
  - recommendation policy engine (deterministic mode)
- Create DB migrations for agent-owned tables in `fraud_gov`.
- Implement idempotency keys and replay-safe write paths.
- Add metrics/logging/tracing scaffolding.

#### `card-fraud-transaction-management`

- Validate all required read fields for Ops Agent context and evidence.
- Add optional read endpoints/filters only if contract gaps exist.
- Confirm DB role grants for Ops Agent read path.

#### `card-fraud-platform`

- ✅ Ops Agent service added to `docker-compose.apps.yml` (port 8003, `platform` profile)
- ✅ Environment variable and secret wiring complete (`OPS_ANALYST_AUTH0_*`, `OPS_AGENT_RULE_MANAGEMENT_BASE_URL`)
- ✅ Locust service updated with `OPS_ANALYST_URL` and `depends_on: ops-analyst-agent`

#### `card-fraud-intelligence-portal`

- ⏳ Read-only insight panel integration for transaction view — **deferred**
- ⏳ Recommendation queue read integration — **deferred**

### Exit Criteria

- ✅ Gate 0 and Gate 1 criteria met.
- ✅ Deterministic quick investigations are functional and auditable.

## Phase 2 - Analyst Actions and Rule Draft Handoff ✅ COMPLETE

### Objectives

- Enable analyst action loop on recommendations.
- Add rule draft package generation/export path.
- Keep governance boundary intact (maker-checker remains external).

### Deliverables by Repository

#### `card-fraud-ops-analyst-agent` ✅ COMPLETE

- ✅ Recommendation status transitions enforced: OPEN→ACKNOWLEDGED/REJECTED, ACKNOWLEDGED→EXPORTED
- ✅ Atomic `update_status_with_guard()` prevents race conditions
- ✅ Rule draft core (pure logic): `assemble_draft_payload()`, `validate_draft_payload()`
- ✅ Rule draft engine (DB-bound adapter): validates rec type/status, supports dry_run
- ✅ Rule draft service: full `create_draft()` + `export_draft()` implementation
- ✅ `RuleManagementClient` (httpx + tenacity, 3 retries) — feature-flagged off (`OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT=false`)
- ✅ Full audit trail: all mutations emit audit events
- ✅ Schema: `RuleDraftPayloadSchema`, `RuleConditionSchema`, `validation_errors`, `export_error` fields

#### `card-fraud-rule-management`

- ⏳ Ingest endpoint for Ops Agent draft packages — **pending separate work item**
- ⏳ Provenance fields (`recommendation_id`, `insight_id`, `source=ops-agent`) — **pending**

#### `card-fraud-intelligence-portal`

- ⏳ Analyst action UI (acknowledge, reject, create draft, export) — **deferred**
- ⏳ Evidence provenance and action timeline panels — **deferred**

#### `card-fraud-transaction-management`

- ⏳ Expose latest Ops Agent insight summary in transaction overview — **optional, deferred**

### Exit Criteria

- ✅ Gate 2 (Security & Data Governance): scope-based authz, audit immutability
- ✅ Gate 3 (Analyst UX): status transitions enforced, draft creation/export wired, human review checkpoints visible
- ⏳ End-to-end draft handoff to RM pending RM ingest endpoint

## Phase 3 - LLM-Hybrid Enablement, Pilot, and Production Hardening ✅ COMPLETE (core)

### Objectives

- Enable bounded LLM reasoning on top of deterministic evidence.
- Run controlled pilot and meet operational KPIs/SLOs.
- Complete hardening for production launch.

### Deliverables by Repository

#### `card-fraud-ops-analyst-agent` ✅ COMPLETE

- ✅ LiteLLM provider abstraction (`LLMProvider` ABC + `LiteLLMProvider`)
  - Supports `anthropic/claude-sonnet-4-5-20250929`, `gpt-4o-mini`, `ollama/llama3.2`
- ✅ Prompt templates: `PromptRegistry`, versioned `investigation_v1` template
- ✅ Redaction/allowlist: `RedactionPolicy` strips PAN, names, addresses, phone, email, IP
- ✅ Consistency checks: severity alignment, evidence grounding, confidence calibration
- ✅ Reasoning engine: full orchestration with fallback (default-on: `OPS_AGENT_ENABLE_LLM_REASONING=true`)
- ✅ Pipeline integration: reasoning result flows into recommendation generation; `model_mode` field in response
- ✅ Graceful fallback: any LLM error → deterministic-only response, never a crash
- ⏳ Runbooks and incident controls — **pending**
- ⏳ Live `LLM_API_KEY` seeded in Doppler — **pending (needed to enable hybrid mode)**

#### `card-fraud-intelligence-portal`

- ⏳ UI labeling for deterministic vs generated narrative — **deferred**
- ⏳ Analyst feedback capture — **deferred**

#### `card-fraud-platform`

- ✅ `OPS_ANALYST_URL` wired in locust service
- ✅ `ops-analyst-agent` service in `apps` profile with health check
- ⏳ Environment-specific rollout flags for pilot gating — **pending prod config**

### Pilot Scope and Promotion

- Start with a controlled subset (tenant, severity, or queue segment).
- Track KPI outcomes:
  - analyst throughput improvement
  - quality lift (true positive handling)
  - stable false-positive behavior
- Promote only after Gate 4 and Gate 5 completion.
- **Current state**: LLM default-on; ensure provider settings (`LLM_PROVIDER`, `LLM_BASE_URL`, `LLM_API_KEY`) are valid in Doppler.

## Cross-Phase Invariants

- Human final authority is always enforced.
- No automatic rule activation by Ops Agent.
- No mutation of TM source-of-truth tables by Ops Agent.
- Every recommendation and action remains auditable.
- Contract changes require docs and ADR updates.
