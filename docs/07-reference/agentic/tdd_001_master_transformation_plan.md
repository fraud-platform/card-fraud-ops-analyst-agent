# TDD-001: Master Transformation Plan

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** ADR-001 through ADR-009

---

## 1. Overview

Transform the card-fraud-ops-analyst-agent from a deterministic linear pipeline into a true LangGraph-based agentic system. Surgical rewrite: preserve proven infrastructure (`app/core/`, `app/utils/`), delete pipeline/agents/services/schemas/routes, rebuild as LangGraph StateGraph with planner → tool → state loop. TM API integration replaces direct SQL reads. LangChain ChatModel replaces LiteLLM for LLM access. Single InvestigationAgent — no multi-agent overhead.

---

## 2. Decisions Made

| Decision | Choice | Rationale |
|----------|--------|-----------|
| Rewrite scope | Surgical — keep `app/core/` infra, rewrite all agent/service/API code | Avoids re-implementing config, auth, DB, logging, metrics, tracing. End result is clean — only what's needed survives. |
| TM API | API-first — replace `ContextReader` SQL with TM HTTP client | TM API is ready; ADR-009 requires it |
| Multi-agent | Single agent only (YAGNI) | ADR-005 is explicitly "future" |
| LLM provider | LangChain ChatModel (`langchain-ollama`, `langchain-anthropic`) | Native LangGraph integration, Ollama support confirmed |
| Orchestration | LangGraph StateGraph | ADR-001 decision |
| Observability | Keep OpenTelemetry + Prometheus, no LangSmith | ADR-001 explicit rejection of LangSmith |

---

## 3. Phase Roadmap

> **Note:** TDD-007 §11 refines this ordering based on TM integration analysis.
> The recommended build order is: State Model → TMClient → Tool Interface →
> LangChain LLM → Migrate Tools → Planner → LangGraph Runtime → Persistence → API → Observability → Tests.
> TMClient is pulled forward to Phase 2 (before tools) because tools depend on it for integration testing.

| Phase | Name | Est. Days | Dependencies |
|-------|------|-----------|--------------|
| 0 | Cleanup & Dependency Setup | 1 | None |
| 1 | Investigation State Model | 1 | Phase 0 |
| 2 | TM API Client | 1 | Phase 0 |
| 3 | Tool Interface & Registry | 1 | Phase 1 |
| 4 | LangChain LLM Integration | 1 | Phase 0 |
| 5 | Migrate Existing Tools (6) | 3 | Phase 2, 3 |
| 6 | Planner Node | 2 | Phase 1, 4 |
| 7 | LangGraph Runtime | 2 | Phase 3, 5, 6 |
| 8 | Persistence & Memory Layer | 2 | Phase 1, 7 |
| 9 | API & Service Layer | 2 | Phase 7, 8 |
| 10 | Observability Integration | 1 | Phase 7 |
| 11 | Testing & Quality Gates | 3 | All |
| **Total** | | **~20 days** | |

---

## 4. What to Keep

| Path | Reason |
|------|--------|
| `app/core/config.py` | All 10 settings classes; add `LangGraphConfig` and `PlannerConfig` sections |
| `app/core/auth.py` | Auth0 JWT, scopes, `require_scope()` — unchanged |
| `app/core/database.py` | Async engine + session factory — unchanged |
| `app/core/errors.py` | `OpsAgentError` hierarchy — unchanged |
| `app/core/logging.py` | structlog setup — unchanged |
| `app/core/metrics.py` | Prometheus counters/histograms — extend with agent metrics |
| `app/core/tracing.py` | ContextVar-based tracing — unchanged |
| `app/core/dependencies.py` | Annotated type aliases — unchanged |
| `app/utils/` | `clock.py`, `idempotency.py`, `hashing.py` — unchanged |
| `app/clients/embedding_client.py` | Ollama embedding client — reuse in SimilarityTool |
| `app/clients/rule_management_client.py` | Rule export client — reuse in RuleDraftTool |
| `app/persistence/base.py` | `row_to_dict()`, `BaseCursor` — unchanged |
| `cli/` | All CLI scripts — update references |
| `db/` | Keep existing migrations, add new ones |
| Pure core logic files | See TDD-003 for which `*_core.py` logic to preserve |

---

## 5. What to Delete

| Path | Reason |
|------|--------|
| `app/agents/pipeline.py` | Linear pipeline replaced by LangGraph graph |
| `app/agents/context_builder.py` | DB-bound adapter replaced by ContextTool |
| `app/agents/pattern_engine.py` | DB-bound adapter replaced by PatternTool |
| `app/agents/similarity_engine.py` | DB-bound adapter replaced by SimilarityTool |
| `app/agents/recommendation_engine.py` | DB-bound adapter replaced by RecommendationTool |
| `app/agents/reasoning_engine.py` | Replaced by ReasoningTool + LangChain LLM |
| `app/agents/rule_draft_engine.py` | Replaced by RuleDraftTool |
| `app/agents/audit_engine.py` | Audit handled by graph persistence layer |
| `app/agents/action_planner.py` | Replaced by LLM planner node |
| `app/agents/conflict_matrix.py` | Absorb into PatternTool or remove |
| `app/agents/evidence_builder.py` | Evidence built within tools + completion node |
| `app/agents/explanation_builder.py` | Absorb into completion node |
| `app/agents/freshness.py` | Move to tool utils |
| `app/agents/pattern_utils.py` | Move to tool utils |
| `app/agents/similarity_utils.py` | Move to tool utils |
| `app/services/investigation_service.py` | Rewrite around graph invocation |
| `app/services/insight_service.py` | Simplify or merge |
| `app/services/recommendation_service.py` | Simplify |
| `app/services/rule_draft_service.py` | Simplify |
| `app/persistence/context_reader.py` | Replaced by TM API client |
| `app/persistence/run_repository.py` | Replace with `investigation_repository` |
| `app/llm/provider.py` | Replace with LangChain ChatModel |
| `app/llm/consistency.py` | Absorb into planner/reasoning tool |
| `app/llm/redaction.py` | Keep and move to `app/utils/` |
| `app/llm/prompts/` | Replace with new planner + tool prompts |
| `app/schemas/v1/` | Rewrite for agentic responses |
| `app/api/routes/investigations.py` | Rewrite for graph-based investigation |
| All `tests/` | Rewrite to match new architecture |

---

## 6. Target Directory Structure

```
app/
├── __init__.py
├── main.py                          # Updated: new routers, lifespan
├── core/                            # PRESERVED (config, auth, db, errors, logging, metrics, tracing)
│   ├── config.py                    # Extended with LangGraphConfig, PlannerConfig
│   └── ...
├── utils/                           # PRESERVED + additions
│   ├── clock.py
│   ├── idempotency.py
│   ├── hashing.py
│   └── redaction.py                 # Moved from app/llm/
├── clients/                         # PRESERVED + TM client added
│   ├── embedding_client.py
│   ├── rule_management_client.py
│   └── tm_client.py                 # NEW: Transaction Management API client
├── agent/                           # NEW: LangGraph agent runtime
│   ├── __init__.py
│   ├── state.py                     # InvestigationState TypedDict
│   ├── graph.py                     # StateGraph construction + compilation
│   ├── planner.py                   # Planner node (LLM-driven tool selection)
│   ├── executor.py                  # Tool execution node
│   ├── completion.py                # Completion node (finalize + persist)
│   ├── registry.py                  # ToolRegistry
│   └── prompts.py                   # Planner prompt templates
├── tools/                           # NEW: Investigation tools
│   ├── __init__.py
│   ├── base.py                      # BaseTool ABC
│   ├── context_tool.py              # TM API context retrieval
│   ├── pattern_tool.py              # Wraps pattern_engine_core
│   ├── similarity_tool.py           # Wraps similarity_engine_core
│   ├── reasoning_tool.py            # LLM reasoning via LangChain
│   ├── recommendation_tool.py       # Wraps recommendation_engine_core
│   ├── rule_draft_tool.py           # Rule draft generation
│   └── _core/                       # Preserved pure logic
│       ├── __init__.py
│       ├── pattern_logic.py         # From pattern_engine_core.py
│       ├── similarity_logic.py      # From similarity_engine_core.py
│       ├── recommendation_logic.py  # From recommendation_engine_core.py
│       ├── context_logic.py         # From context_builder_core.py
│       ├── reasoning_logic.py       # From reasoning_core.py
│       ├── rule_draft_logic.py      # From rule_draft_core.py
│       ├── freshness.py             # From agents/freshness.py
│       ├── pattern_utils.py         # From agents/pattern_utils.py
│       └── similarity_utils.py      # From agents/similarity_utils.py
├── llm/                             # NEW: LangChain LLM layer
│   ├── __init__.py
│   └── provider.py                  # LangChain ChatModel factory
├── persistence/                     # EVOLVED
│   ├── __init__.py
│   ├── base.py                      # PRESERVED
│   ├── investigation_repository.py  # NEW: replaces run_repository
│   ├── state_store.py               # NEW: JSONB state persistence
│   ├── tool_log_repository.py       # NEW: tool execution log
│   ├── insight_repository.py        # SIMPLIFIED
│   ├── recommendation_repository.py # SIMPLIFIED
│   ├── rule_draft_repository.py     # PRESERVED
│   └── audit_repository.py          # PRESERVED
├── schemas/v1/                      # REWRITTEN
│   ├── __init__.py
│   ├── common.py                    # Enums, ApiError
│   ├── health.py                    # Preserved
│   ├── state.py                     # InvestigationState schema
│   ├── investigations.py            # Run/Detail responses with tool traces
│   ├── tools.py                     # Tool execution DTOs
│   └── recommendations.py          # Simplified
├── services/                        # SIMPLIFIED
│   ├── __init__.py
│   ├── investigation_service.py     # Thin: invokes graph, returns result
│   └── recommendation_service.py    # Worklist query + acknowledge
└── api/routes/                      # SIMPLIFIED
    ├── __init__.py
    ├── health.py                    # PRESERVED
    ├── monitoring.py                # PRESERVED
    ├── investigations.py            # Rewritten for graph invocation
    └── recommendations.py           # Simplified worklist
```

---

## 7. Dependency Changes

### Add

| Package | Purpose |
|---------|---------|
| `langgraph >= 0.3.0` | Graph orchestration runtime |
| `langchain-core >= 0.3.0` | LangGraph dependency, base abstractions |
| `langchain-anthropic >= 0.3.0` | Anthropic ChatModel for planner |
| `langchain-ollama >= 0.3.0` | Ollama ChatModel for local dev |

### Remove

| Package | Reason |
|---------|--------|
| `litellm` | Replaced by LangChain providers |

### Keep (Unchanged)

`fastapi`, `uvicorn`, `pydantic`, `pydantic-settings`, `sqlalchemy`, `asyncpg`, `psycopg`, `python-jose`, `structlog`, `opentelemetry-*`, `prometheus-client`, `httpx`, `orjson`, `tenacity`

---

## 8. Verification

After each phase, run quality gates:

```bash
uv run ruff check app/ tests/ cli/ scripts/
uv run ruff format --check app/ tests/ cli/ scripts/
uv run pytest tests/unit tests/smoke -v
```

---

## 9. Risk Mitigation

| Risk | Mitigation |
|------|-----------|
| Planner makes incorrect tool decisions | Constrained prompt + rule-based fallback + max_steps limit |
| LLM latency increases investigation time | 30s timeout on graph, 10s timeout per tool, deterministic fallback |
| State corruption during graph execution | Transactional persistence after every step, versioned state |
| TM API unavailability | Circuit breaker + retry in `tm_client.py` |
| Breaking existing integrations | Phase 0 creates clean break; no gradual migration (complete rewrite) |

---

## 10. Success Criteria

- All investigations complete within 30 seconds
- Planner selects appropriate tools ≥90% of the time
- Full audit trail for every investigation (planner decisions + tool executions)
- Zero regressions on fraud detection quality
- All quality gates pass (lint, format, unit, smoke)
- State resume works after simulated failures
