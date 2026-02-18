# Non-Functional Test Plan

## Performance Targets

- Quick run endpoint P95 <= 2s.
- Deep run endpoint P95 <= 8s.
- Recommendation queue endpoint P95 <= 500ms at target load.

## Reliability Targets

- API error rate < 1% excluding client errors.
- No data corruption under retries.
- Replay and idempotency behavior validated for duplicate triggers.

## Security and Compliance Targets

- Zero critical leakage findings for LLM payload boundary.
- 100% mutating actions generate audit records.
- RBAC tests cover all endpoint/scope combinations.

## Observability Targets

- Every investigation has a run identifier.
- Trace continuity across service boundaries where available.
- Metrics emitted for success/failure, latency, and queue depth.

## Test Execution Windows

- Baseline run against local platform stack.
- Soak profile at representative analyst workload.
- Failure-injection runs for dependency degradation.
