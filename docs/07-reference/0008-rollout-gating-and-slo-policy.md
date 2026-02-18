# ADR 0008: Rollout Gating and SLO Policy

## Status

Accepted

## Context

Production-grade agentic systems need explicit readiness gates and measurable reliability targets.

## Decision

Adopt staged rollout gates (`Gate 0` to `Gate 5`) and enforce defined SLO thresholds before promotion.

## Consequences

- Clear release discipline.
- Reduced production risk.
- Additional pre-release validation effort required.
