# ADR 0001: Transaction Management as Source of Truth

## Status

Accepted

## Context

There was a choice between event-first ingestion and TM-centric source-of-truth access for Ops Agent.

## Decision

Ops Agent v1 will use Transaction Management data (`fraud_gov` + TM APIs) as source of truth.
Kafka direct consumption is optional for later phases.

## Consequences

- Simpler operational model in v1.
- Reduced dual-write and consistency risk.
- Clear analyst alignment with existing workflows.
