# Comprehensive Review & Agentic AI Cleanup Plan

**Date:** 2026-02-22
**Purpose:** Complete the LangGraph agentic transformation, clean up old code, fix bugs, update docs

---

## Context

The project is mid-transformation from a linear deterministic pipeline to a LangGraph-based agentic AI system. The old pipeline code has been deleted from the working tree (git shows `D` for `app/agents/*`, old services, etc.), and the new agentic code is in place under `app/agent/`, `app/tools/`, `app/clients/tm_client.py`, etc. However, the transformation is **incomplete** — there are gaps in implementation, stale docs, backward-compatibility artifacts, and missing test coverage for the new code. The old version is already pushed to GitHub, so this version should be **purely agentic**.

---

## 1. Architecture Assessment (Current State)

### What's DONE (working agentic code)
- `app/agent/state.py` — InvestigationState TypedDict, `create_initial_state()`, `update_state()`
- `app/agent/graph.py` — LangGraph StateGraph: planner → tool_executor → completion loop
- `app/agent/planner.py` — LLM-driven tool selection with JSON output
- `app/agent/executor.py` — Tool execution with timeout, metrics, tracing
- `app/agent/completion.py` — Finalize investigation, compute confidence/severity, persist state
- `app/agent/registry.py` — ToolRegistry for tool lookup
- `app/tools/base.py` — BaseTool ABC (name, description, execute)
- `app/tools/context_tool.py` — TM API integration via TMClient
- `app/tools/pattern_tool.py` — Fraud pattern scoring (deterministic)
- `app/tools/similarity_tool.py` — Vector similarity search via Ollama embeddings
- `app/tools/reasoning_tool.py` — LLM-powered reasoning via LangChain ChatModel
- `app/tools/recommendation_tool.py` — Generate recommendations from evidence
- `app/tools/rule_draft_tool.py` — Generate rule drafts
- `app/tools/_core/*.py` — Pure logic files (preserved from old codebase)
- `app/clients/tm_client.py` — TM API client with retry, circuit breaker, field remapping
- `app/llm/provider.py` — LangChain ChatModel factory (Ollama + Anthropic)
- `app/services/investigation_service.py` — Graph orchestration service
- `app/services/recommendation_service.py` — Worklist management
- `app/persistence/investigation_repository.py` — Investigation CRUD
- `app/persistence/state_store.py` — JSONB state persistence
- `app/persistence/tool_log_repository.py` — Tool execution audit log
- `app/api/routes/investigations.py` — Run/get/resume endpoints
- `app/api/routes/recommendations.py` — Worklist endpoints
- `app/schemas/v1/investigations.py` — Agentic response schemas

### What's PRESERVED (infrastructure — keep as-is)
- `app/core/*` (config, auth, database, errors, logging, metrics, tracing, dependencies)
- `app/utils/*` (clock, hashing, idempotency, redaction, dataclass_utils)
- `app/clients/embedding_client.py`, `app/clients/rule_management_client.py`
- `app/persistence/base.py`, `app/persistence/audit_repository.py`
- `app/persistence/insight_repository.py`, `app/persistence/recommendation_repository.py`
- `cli/*`, `db/*`, `scripts/*`

---

## 2. Issues Found

### 2.1 Code Issues (Bugs & Mismatches)

| # | File | Issue | Severity |
|---|------|-------|----------|
| A1 | `app/api/routes/investigations.py:69` | **Syntax error**: `except ValueError, TypeError:` — Python 2 syntax, should be `except (ValueError, TypeError):` | CRITICAL |
| A2 | `app/services/investigation_service.py` | **Missing post-graph persistence**: After graph completion, tool_executions, insights, recommendations, and rule_drafts are NOT persisted to their respective DB tables. Only state_store and investigation row are updated. | HIGH |
| A3 | `app/persistence/tool_log_repository.py:36` | Column name mismatch: INSERT uses `id` but migration DDL has `log_id` for PK — INSERT will fail | CRITICAL |
| A4 | `app/persistence/recommendation_repository.py` | **Code uses wrong column names**: INSERT references `recommendation_type` and `recommendation_payload`, but DDL has `type` and `payload` — INSERT will fail | CRITICAL |
| A5 | `app/persistence/insight_repository.py` | **Code uses wrong column name**: INSERT references `insight_summary`, but DDL has `summary` — INSERT will fail | CRITICAL |
| A5b | `app/persistence/rule_draft_repository.py` | **Completely wrong schema**: references `draft_package_version`, `draft_payload` columns that don't exist. DDL has `rule_name`, `rule_description`, `conditions`, `thresholds`, `metadata` | CRITICAL |
| A5c | `app/schemas/v1/common.py` | `RunMode` enum has `quick`/`deep` but `RunRequest.mode` defaults to `"FULL"` — enum not used for validation | LOW |
| A6 | `pyproject.toml:4` | Description says "deterministic evidence pipeline" — should say "LangGraph-based agentic fraud investigation" | LOW |
| A7 | `README.md:16` | Still references "LiteLLM" — should reference LangChain + Ollama | MEDIUM |
| A8 | `app/schemas/v1/recommendations.py:17` | Forward reference: `RecommendationListResponse` references `RecommendationDetail` before it's defined | HIGH |
| A9 | `AGENTS.md:32` | Still says "deterministic evidence analysis" and "Phase 1-3 complete" | MEDIUM |

### 2.2 Missing Implementations

| # | Component | What's Missing |
|---|-----------|---------------|
| B1 | Post-graph persistence | `InvestigationService.run_investigation()` needs to persist tool_executions → `tool_log_repository`, insights → `insight_repository`, recommendations → `recommendation_repository`, rule_drafts → `rule_draft_repository` after graph completes |
| B2 | LLM metrics instrumentation | `reasoning_tool.py` and `planner.py` don't emit `ops_agent_llm_calls_total`, `ops_agent_llm_latency_seconds`, or `ops_agent_llm_tokens_total` metrics |
| B3 | Investigation list endpoint | No `GET /investigations` list endpoint (only get-by-id) |
| B4 | Insights endpoint | Old `app/api/routes/insights.py` was deleted but no replacement — need `GET /transactions/{id}/insights` |
| B5 | Rule drafts endpoint | Old `app/api/routes/rule_drafts.py` was deleted but no replacement |
| B6 | Tool execution tests | No unit tests for individual tools (context_tool, pattern_tool, reasoning_tool, etc.) |
| B7 | Planner/executor/completion tests | No unit tests for graph nodes |
| B8 | Graph integration test | No test that runs the full graph end-to-end with mocks |
| B9 | Smoke tests for new endpoints | Smoke tests likely broken due to route changes |
| B10 | State store metrics | `ops_agent_state_store_latency_seconds` defined but never emitted |

### 2.3 Logging / Monitoring / Tracing Gaps

| # | Area | Issue |
|---|------|-------|
| C1 | Planner tracing | Planner node has OTel spans but doesn't record LLM prompt/response token counts |
| C2 | Reasoning tool tracing | No OTel span wrapping the LLM call in reasoning_tool |
| C3 | Investigation service | No Prometheus metrics for investigation_requests_total or investigation_latency_seconds |
| C4 | Context tool | No metrics for TM API calls from context_tool (TMClient already has metrics, but tool-level is missing) |
| C5 | State store | save_state/load_state don't emit latency metrics |
| C6 | Structured logging | Some tools use `structlog` but reasoning_tool doesn't log anything |

### 2.4 Security / Auditability Gaps

| # | Area | Issue |
|---|------|-------|
| D1 | Audit trail | Investigation lifecycle (create → in_progress → completed) is not written to `ops_agent_audit_log` |
| D2 | Redaction | `redact_state_for_llm()` only handles context.transaction.card_id — doesn't redact card_history individual card_ids or notes |
| D3 | Input validation | `RunRequest` validates UUID format but no rate limiting or duplicate detection at API level |
| D4 | Tool execution logging | Tool executions are tracked in state but NOT persisted to `ops_agent_tool_execution_log` after graph completion |
| D5 | PII in state store | Full state (including card_id, transaction details) is stored as JSONB — should redact PII before persistence |

### 2.5 Explainability Gaps

| # | Area | Issue |
|---|------|-------|
| E1 | Planner reasoning | Planner decisions (why each tool was chosen) are in state but not surfaced in API responses effectively |
| E2 | Evidence chain | Evidence list in state captures tool outputs but lacks a unified narrative |
| E3 | Confidence breakdown | Final confidence is averaged but doesn't explain which component contributed what |
| E4 | Severity escalation | When reasoning_tool upgrades severity, there's no audit trail of the change |

---

## 3. Documentation Cleanup

### Docs to DELETE (stale/old pipeline references)
- `docs/07-reference/agentic/README.md (legacy phase plan removed)` — old Phase 1 plan
- `docs/archive/` — entire directory (old plans, improvement docs)
- `legacy ADR 0004 (deleted)` — replaced by agentic architecture
- `legacy ADR 0007 (deleted)` — LiteLLM replaced by LangChain
- `legacy ADR 0009 (deleted)` — LiteLLM-era doc
- `docs/codemap.md` — stale, references old pipeline
- `CODEMAP.md` — root-level duplicate
- `DEVELOPER_GUIDE.md` — likely stale

### Docs to UPDATE
- `README.md` — Update stack description (LangChain, not LiteLLM), update architecture diagram
- `AGENTS.md` — Update to reflect agentic architecture, not "deterministic evidence pipeline"
- `docs/README.md` — Update section index if docs are removed
- `docs/02-development/architecture.md` — Must describe LangGraph planner→executor→completion loop
- `docs/02-development/agent-workflow-and-orchestration.md` — Must describe agentic workflow
- `docs/03-api/ops-agent-api-contract-v1.md` — Must reflect new endpoints
- `docs/03-api/openapi-outline.md` — Must reflect new routes
- `docs/05-deployment/config-and-feature-flags.md` — Add LangGraph, Planner, TMClient configs
- `docs/06-operations/observability.md` — Add agentic metrics (planner decisions, tool executions)

### Docs to CREATE
- `docs/02-development/langgraph-agent-architecture.md` — New architecture doc from ADRs
- Move `docs/07-reference/agentic/` ADRs/TDDs into `docs/07-reference/` as canonical ADRs

---

## 4. Files to Clean Up

### Delete (backward-compatibility artifacts / dead code)
- `app/llm/prompts/` directory — deleted in git but verify no references
- `app/llm/consistency.py` — deleted in git, verify no references
- `app/llm/redaction.py` — deleted, replaced by `app/utils/redaction.py`
- `nul` — Windows artifact file at root
- `coverage.json` — should be in .gitignore

### Verify deleted (git status shows `D` — confirm no lingering references)
- All `app/agents/*.py` files
- `app/persistence/context_reader.py`
- `app/persistence/run_repository.py`
- All old test files (`tests/unit/test_*` for old modules)

---

## 5. Implementation Plan (Ordered by Priority)

### Phase A: Critical Fixes (must fix before anything works)

1. **Fix syntax error** in `investigations.py:69`
   - `except ValueError, TypeError:` → `except (ValueError, TypeError):`

2. **Fix schema column mismatches** — align code to match migration DDL
   - `tool_log_repository.py`: `id` → `log_id`
   - `insight_repository.py`: `insight_summary` → `summary`
   - `recommendation_repository.py`: `recommendation_type` → `type`, `recommendation_payload` → `payload`
   - `rule_draft_repository.py`: Complete rewrite to match DDL schema (`rule_name`, `rule_description`, `conditions`, `thresholds`, `metadata`, `investigation_id`)

3. **Fix forward reference** in `recommendations.py` — reorder classes so `RecommendationDetail` is defined before `RecommendationListResponse`

### Phase B: Post-Graph Persistence (core missing feature)

4. **Add `_persist_results()` to InvestigationService**
   - After graph completion, extract from final state:
     - `tool_executions` → `ToolLogRepository.log_execution()` for each
     - Create insight from reasoning + evidence → `InsightRepository.upsert_insight()`
     - Create recommendations → `RecommendationRepository.upsert_recommendation()`
     - Create rule draft → `RuleDraftRepository` (if present in state)
   - Add audit log entries for investigation lifecycle

### Phase C: Missing API Endpoints

5. **Add insights route** — `GET /api/v1/ops-agent/transactions/{txn_id}/insights`
6. **Add investigation list** — `GET /api/v1/ops-agent/investigations`
7. **Add rule drafts route** — `GET /api/v1/ops-agent/investigations/{id}/rule-draft`

### Phase D: Observability Instrumentation

8. **Add LLM metrics** to planner and reasoning tool
   - Emit `ops_agent_llm_calls_total`, `ops_agent_llm_latency_seconds`
   - Record token usage via `ops_agent_llm_tokens_total`
9. **Add state store metrics** — emit `ops_agent_state_store_latency_seconds` on save/load
10. **Add investigation-level metrics** — emit `ops_agent_investigation_requests_total` and `ops_agent_investigation_latency_seconds`
11. **Add OTel spans** to reasoning_tool for LLM calls
12. **Add structured logging** to all tools consistently (reasoning_tool, recommendation_tool, rule_draft_tool)

### Phase E: Security & Auditability

13. **Add audit logging** for investigation lifecycle events (create, status transitions, completion)
14. **Enhance PII redaction** — redact card_ids in card_history, notes content before LLM and state store persistence
15. **Tool execution DB persistence** (covered in Phase B)

### Phase F: Test Coverage

16. **Unit tests for each tool** (context, pattern, reasoning, recommendation, rule_draft, similarity)
17. **Unit tests for graph nodes** (planner, executor, completion)
18. **Integration test for full graph** (mocked dependencies)
19. **Update smoke tests** for new route structure (`/api/v1/ops-agent/investigations/run`, etc.)
20. **Verify existing tests still pass** after changes

### Phase G: Documentation

21. **Delete stale docs** — archive dir, old plans, LiteLLM ADRs
22. **Update README.md** — agentic description, LangChain + Ollama stack
23. **Update AGENTS.md** — agentic architecture description
24. **Create architecture doc** — `docs/02-development/langgraph-agent-architecture.md` from ADRs
25. **Move ADRs** from `docs/07-reference/agentic/` → `docs/07-reference/`
26. **Update API contract docs** — reflect new endpoints and schemas
27. **Update config docs** — add LangGraph, Planner, TMClient configuration sections
28. **Delete artifacts** — `nul`, `coverage.json` from repo root

### Phase H: Final Cleanup

29. **Update `pyproject.toml`** — description, verify no stale deps
30. **Remove litellm dependency** if still referenced in `uv.lock`
31. **Clean up enums** in `app/schemas/v1/common.py` — align `RunMode` with actual usage
32. **Verify `app/schemas/v1/rule_drafts.py`** — matches new DDL schema

---

## 6. Verification

After all changes:
```bash
# Quality gates
uv run ruff check app/ tests/ cli/ scripts/
uv run ruff format --check app/ tests/ cli/ scripts/
uv run pytest tests/unit -v
uv run pytest tests/smoke -v

# Coverage
uv run pytest tests/ --cov=app --cov-report=term-missing
```

---

## 7. Key Files to Modify

| File | Change Type |
|------|-------------|
| `app/api/routes/investigations.py` | Fix syntax error, add list endpoint |
| `app/services/investigation_service.py` | Add post-graph persistence |
| `app/api/routes/insights.py` | CREATE — new insights endpoint |
| `app/schemas/v1/recommendations.py` | Fix forward reference |
| `app/agent/planner.py` | Add LLM metrics |
| `app/tools/reasoning_tool.py` | Add OTel spans, metrics, logging |
| `app/persistence/tool_log_repository.py` | Fix column name `id` → `log_id` |
| `app/persistence/insight_repository.py` | Fix column name `insight_summary` → `summary` |
| `app/persistence/recommendation_repository.py` | Fix column names `recommendation_type` → `type`, etc. |
| `app/persistence/rule_draft_repository.py` | Complete rewrite to match DDL |
| `app/persistence/state_store.py` | Add latency metrics |
| `db/ops_agent_schema.sql` | Verify is canonical reference |
| `README.md` | Update for agentic architecture |
| `AGENTS.md` | Update for agentic architecture |
| `pyproject.toml` | Update description |
| Multiple docs files | Update/delete per Section 3 |
| Multiple test files | CREATE — per Phase F |
