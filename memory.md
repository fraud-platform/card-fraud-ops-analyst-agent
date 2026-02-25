# memory

Updated: 2026-02-22

## Operational Learnings

- Always run E2E against Dockerized ops-agent on `http://localhost:8003` to avoid stale local uvicorn behavior.
- Keep matrix JSON and HTML synchronized; regenerate HTML after each matrix run.
- Pre-commit needs both hook types to fully enforce policy:
  - `pre-commit` for lint/format/unit/smoke
  - `pre-push` for integration tests via Doppler
- Do not unconditionally `session.rollback()` after LangGraph completion; it discards persisted investigation state and empties detail traces.
- Persisted LangGraph state contains dataclasses/datetime values; state store JSON serialization must support dataclass + datetime + UUID conversion.
- E2E reporter extraction must follow current detail schema (`reasoning`, `evidence`, `planner_decisions`, `tool_executions`) rather than legacy `insight` field.
- Reasoning tool prompt serialization needs `json.dumps(..., default=str)` to avoid datetime serialization failures.

## Fraud Logic Findings (latest matrix)

- Structured evidence and full trace are now present in detail responses across all 31 scenarios.
- Likely-fraud scenarios are now producing recommendations in matrix runs.
- Remaining logic gap: 2 velocity-burst fraud scenarios still underclassify to LOW severity.

## Next Focus

1. Tune velocity-burst thresholds/severity calibration to eliminate remaining 2 underclassified fraud cases.
2. Stabilize planner LLM provider integration (remove provider response-shape validation errors).
3. Keep 31-scenario matrix as regression gate and fail when fraud-underclassification is non-zero.
