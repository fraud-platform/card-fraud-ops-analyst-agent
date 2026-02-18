# ADR 0006: Rule Draft Package + Maker-Checker Handoff

## Status

Accepted

## Context

Ops Agent must help with rule operations without bypassing governance controls.

## Decision

Ops Agent generates structured draft rule packages and exports them to Rule Management draft flow.
Final approval and activation remain in maker-checker workflow.

## Consequences

- Higher operational usefulness for analysts.
- Governance boundary preserved.
- Requires stable draft package schema and provenance links.
