# ADR 0004: Hybrid Deterministic + LLM Pipeline

## Status

Accepted

## Context

Fully deterministic systems are explainable but limited in narrative utility.
LLM-only systems are less controllable and harder to audit for decision-critical workflows.

## Decision

Use deterministic evidence generation as the primary layer, then bounded LLM reasoning for supplemental narrative and recommendation framing.

## Consequences

- Better analyst UX without sacrificing evidence integrity.
- Need explicit consistency checks and model governance.
