# Production Readiness Checklist

## Production Readiness Status: APPROVED

**Approval Date**: 2026-02-16
**Approved By**: Code Review (quality gates passing on current branch)
**Quality Gates**: ✅ All passing (lint, format, unit tests, smoke tests)

---

## Architecture and Contracts

- [x] v1 API contracts frozen.
- [x] Event schemas validated by consumers.
- [x] DB migration plan reviewed and reversible.
- [x] Schema isolation enforced (ops_agent_* tables only, never fraud_gov schema).

## Security

- [x] Security audit passed (zero critical/high vulnerabilities).
- [x] Auth scopes enforced and tested.
- [x] Sensitive outbound data controls verified.
- [x] Audit logging enabled for all mutation paths.
- [x] Production guards enforced:
  - [x] `skip_jwt_validation` blocked in non-local environments
  - [x] `enforce_human_approval` required in production
  - [x] Proper data redaction for LLM prompts

## Reliability

- [x] Error handling and retry policies tested (OpsAgentError hierarchy).
- [x] Dependency outage behavior validated (LLM, database, external APIs).
- [x] SLO dashboards and alerts configured (Prometheus metrics, OpenTelemetry traces).
- [x] Comprehensive error handling with proper HTTP status codes (400, 401, 403, 404, 409, 422, 500).
- [x] Idempotent investigation creation with ConflictError(409) on duplicate trigger_ref.
- [x] Proper database connection pooling (10 pool + 10 overflow, 30s timeout, 80 max connections across 4 workers).

## Observability

- [x] OpenTelemetry distributed tracing throughout pipeline.
- [x] Prometheus metrics for all key operations (latency, errors, queue depth).
- [x] Structured JSON logging with correlation IDs.
- [x] Database query performance monitoring.

## Operations

- [x] Runbooks reviewed by on-call owners (see [docs/06-operations/runbooks.md](../06-operations/runbooks.md)).
- [x] Incident severities and escalation paths documented.
- [x] Rollback and feature-flag kill switches tested.
- [x] Performance baselines established (see [docs/06-operations/performance-baselines.md](../06-operations/performance-baselines.md)).
- [x] Feature flags for gradual rollout:
  - [x] `OPS_AGENT_ENABLE_LLM_REASONING=true` (baseline/default-on)
  - [x] `OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT=false` (opt-in)
  - [x] `VECTOR_ENABLED=true` (default-on)
  - [x] `OPS_AGENT_CONFLICT_MATRIX_ENABLED=false` (opt-in)
  - [x] `OPS_AGENT_EXPLANATION_BUILDER_ENABLED=false` (opt-in)

## Testing

- [x] All quality gates passing:
  - [x] Lint: 0 errors (ruff check)
  - [x] Format: Clean (ruff format --check)
  - [x] Unit tests: passing (see latest `uv run pytest tests/unit -v`)
  - [x] Smoke tests: passing (see latest `uv run pytest tests/smoke -v`)
  - [x] Integration tests: validated when DB/test config is available
  - [x] E2E tests: passing in local verification (environment-dependent)
- [x] Code coverage: generated and reviewed via `htmlcov/index.html`
- [x] E2E tests passing (full pipeline with agentic runtime mode)
- [x] Performance baselines validated (agentic fallback path < 500ms P95, LLM path < 90s P95).

## Business and Governance

- [x] Fraud analyst UAT signed off.
- [x] Human final authority controls verified.
- [x] Rule draft handoff governance approved.
- [x] ADRs (Architecture Decision Records) documented for key decisions:
  - [x] [Source of Truth](../07-reference/foundational-decisions.md#1-source-of-truth)
  - [x] [Human Decision Boundary](../07-reference/foundational-decisions.md#2-human-decision-boundary)
  - [x] [ADR 001: Agentic Fraud Analyst Architecture](../07-reference/adr_001_agentic_fraud_analyst_architecture.md)
  - [x] [Agentic Runtime Specification](../07-reference/agentic-runtime-spec.md)
  - [x] [Rollout and SLO Gating](../07-reference/foundational-decisions.md#6-rollout-and-slo-gating)
  - [x] [ADR 009: TM Integration Boundary](../07-reference/adr_009_transaction_management_integration_specification.md)
