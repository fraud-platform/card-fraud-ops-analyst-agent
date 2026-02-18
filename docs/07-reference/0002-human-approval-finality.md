# ADR 0002: Human Final Approval Boundary

## Status

Accepted

## Context

The product is autonomous-assist, not autonomous-decision, in regulated fraud operations.

## Decision

All final fraud outcomes and rule activation outcomes remain human-controlled.
Ops Agent can suggest and draft, but cannot finalize.

## Consequences

- Strong governance alignment.
- Reduced model-risk blast radius.
- Slightly slower automation, higher operational safety.
