# ADR-009: Transaction Management Integration Boundary

## Status

Accepted

## Context

Ops Analyst Agent requires transaction, card-history, merchant-history, review, and rule-match context.
Transaction Management (TM) is the system of record for this domain data.

## Decision

Ops Agent integrates with TM via TM API contracts through `TMClient`.

Primary calls:

- `GET /api/v1/transactions/{transaction_id}/overview`
- `GET /api/v1/transactions?card_id=...`
- `GET /api/v1/transactions?merchant_id=...`
- `GET /api/v1/health`

Operational behaviors:

- retry transient connection failures,
- circuit breaker for repeated TM dependency failures,
- bounded pagination for history retrieval,
- short-lived in-memory caching for repeated history calls.

## Data Boundary

- TM domain data is read via TM API.
- Ops Agent persists only agent-owned artifacts in `ops_agent_*` tables.
- Fraud disposition and review ownership remain outside ops-agent write domain.

## Security and Reliability Constraints

- authenticated service-to-service traffic (environment-specific auth controls),
- strict timeout and retry policy,
- dependency failure metrics and traces for incident diagnosis.

## Consequences

Positive:

- clear source-of-truth boundary,
- lower dual-write risk,
- easier cross-repo governance.

Trade-offs:

- runtime dependency on TM availability and latency,
- requires robust fallback behavior and observability.
