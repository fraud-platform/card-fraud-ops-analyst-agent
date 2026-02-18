# Acceptance Test Matrix

## Legend

- Priority: `P0` critical, `P1` high, `P2` medium.
- Type: `F` functional, `S` security, `N` non-functional.

| ID | Priority | Type | Scenario | Expected Result |
|---|---|---|---|---|
| AT-001 | P0 | F | Run quick investigation by transaction ID | Run succeeds with insight + recommendation payload |
| AT-002 | P0 | F | Run deep investigation by transaction ID | Run succeeds with expanded evidence and explanation |
| AT-003 | P0 | F | Acknowledge recommendation | Status changes to `ACKNOWLEDGED` with actor/time audit |
| AT-004 | P0 | F | Reject recommendation | Status changes to `REJECTED` with audit |
| AT-005 | P0 | F | Create rule draft package from recommendation | Draft payload stored and schema-valid |
| AT-006 | P0 | F | Export draft package to Rule Management | Export result persisted and traceable |
| AT-007 | P0 | S | Call mutating endpoint without required scope | `403` returned and no mutation |
| AT-008 | P0 | S | Prompt payload includes blocked sensitive field | Request blocked/sanitized per policy with audit marker |
| AT-009 | P1 | N | Load quick investigation path at expected concurrency | P95 latency <= 2s |
| AT-010 | P1 | N | Load deep investigation path at expected concurrency | P95 latency <= 8s |
| AT-011 | P1 | F | Replay same run trigger | No duplicate recommendation for same idempotency key |
| AT-012 | P1 | F | TM dependency outage during run | Graceful failure and `FAILED` run state with error summary |
| AT-013 | P2 | F | Empty evidence case | Recommendation may be absent; explanation indicates insufficient evidence |
| AT-014 | P2 | N | Recommendation queue pagination at scale | Stable cursor behavior and correct item ordering |

## Completion Rule

All `P0` scenarios must pass before implementation phase exit.
