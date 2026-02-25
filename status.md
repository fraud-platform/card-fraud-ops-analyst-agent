# status

Updated: 2026-02-23

## Current State

**31/31 E2E COMPLETED · 208 tests pass · 0 lint errors**

## E2E Matrix (final, fresh DB, post simplifier + bug fixes)

```
status_counts={'COMPLETED': 31}
run_p95:    25515.2 ms
detail_p95:    66.6 ms
run_avg:    17253.8 ms
```

Quality issues (not failures — all investigations complete):
| Issue | Count | Notes |
|---|---|---|
| `no_fraud_overescalated` | 6/9 | recommendation_tool emits action on legitimate txns |
| `fraud_underclassified_low` | 2/13 | LOW severity on high-signal fraud |
| `summary_recommendation_contradiction` | 3/31 | narrative and rec type disagree |

## Changes Completed This Session (2026-02-23)

### Planner hardening
- Fixed `PlannerError(response_content=...)` TypeError → crash with `planner_steps=0`
- LLM repeated-tool selection → deterministic fallback instead of raise
- 2 new tests; import time moved to module level by simplifier

### Code simplifier (app/agent, app/llm, app/tools, app/services)
- executor.py: extracted `_create_execution_record`, `_record_metrics`, `_append_step` helpers (~60 lines removed)
- planner.py: moved `import time` to module level
- reasoning_logic.py: extracted `_resolve_field` helper (~50 lines removed)
- rule_draft_tool.py: logger at module level, simplified evidence list construction
- context_tool.py: extracted `_extract_result` helper
- reasoning_tool.py, pattern_tool.py, similarity_tool.py, recommendation_tool.py: moved `update_state` import to module level
- investigation_service.py: made `_compute_insight_key`, `_compute_recommendation_key` static
- provider.py: simplified headers construction, cleaned retry loop variables

### Bug fixes from code-reviewer (H3, H4, H6, M9)
- **H3/H4**: Extracted `_complete_investigation()` helper with rollback-retry and second-attempt guard; both `run_investigation` and `resume_investigation` now use it
- **H6**: `model_mode` now derived from `state["feature_flags"]["reasoning_llm_enabled"]` instead of hardcoded `"hybrid"`
- **M9**: `httpx.AsyncClient` moved outside retry loop (single TCP/TLS connection per call)

## Open Quality Issues

- `no_fraud_overescalated`: recommendation_tool always emits an action — needs context-aware suppression for clear no-fraud signals
- Latency p95 = 25.5s (2 Ollama cloud thinking-model calls per investigation)
