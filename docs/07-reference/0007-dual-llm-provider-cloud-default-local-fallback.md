# ADR 0007: Dual LLM Provider Strategy

## Status

Accepted

## Context

Need high-quality managed model support and optional local fallback for regulated or outage scenarios.

## Decision

Use cloud model provider by default with local provider fallback path.
Both providers must receive the same policy-filtered prompt payload shape.

## Consequences

- Better resiliency and deployment flexibility.
- Extra operational complexity for provider abstraction and regression testing.
