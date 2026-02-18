# ADR 0005: Redaction and Pseudonym Correlation Policy

## Status

Accepted

## Context

Analyst-quality correlation requires stable identifiers, but prompt payloads must avoid sensitive leakage.

## Decision

Allow stable pseudonymous identifiers (tokenized/hashed card IDs, merchant IDs, device hashes) in model context.
Block direct sensitive personal fields and unbounded raw payloads.

## Consequences

- Maintains correlation utility.
- Reduces privacy and compliance risk.
- Requires allowlist enforcement and policy tests.
