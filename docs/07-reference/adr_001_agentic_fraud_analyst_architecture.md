# ADR-001: Agentic LangGraph Runtime for Fraud Investigation

## Status

Accepted

## Dates

- Decision date: 2026-02-19
- Implemented: 2026-02-23

## Context

The earlier implementation used a fixed linear investigation pipeline.
That design limited adaptive investigation depth and made tool sequencing rigid.

Fraud operations requires stateful, evidence-driven execution where the system can:

- choose next steps based on intermediate evidence,
- preserve a full trace of planning and execution,
- degrade safely when model/dependency calls fail.

## Decision

Use LangGraph as the runtime orchestrator with:

- planner node for next-action selection,
- executor node for bounded tool execution,
- completion node for finalization and persistence.

The runtime remains governance-constrained:

- human analysts keep final fraud decision authority,
- rule activation stays in maker-checker flow,
- all agent outputs are advisory.

## Consequences

Positive:

- adaptive tool orchestration per investigation,
- stronger auditability (`planner_decisions`, `tool_executions`, evidence trail),
- safer degradation path through fallback behaviors.

Trade-offs:

- higher runtime variance due to live LLM calls,
- stricter timeout/fallback design required to keep E2E reliability.

## Implementation Notes

- Canonical runtime behavior is documented in `agentic-runtime-spec.md`.
- TM integration boundary is documented in `adr_009_transaction_management_integration_specification.md`.
