# ADR 0003: Shared `fraud_gov` Schema with Agent-Owned Tables

## Status

Accepted

## Context

Using a new schema adds boundary clarity but increases cross-schema complexity and governance overhead.

## Decision

Keep v1 agent artifacts in dedicated `fraud_gov` tables with strict ownership and privileges.

## Consequences

- Easier joins and reporting.
- Lower migration and role complexity.
- Requires careful table naming and privilege controls.
