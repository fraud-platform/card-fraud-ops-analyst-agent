# Foundational Decisions (Ops Analyst Agent)

Concise architecture and governance decisions that remain active for this repository.

## 1) Source of Truth

- Transaction context comes from Transaction Management (TM) data and TM APIs.
- Direct Kafka ingestion is not part of current ops-agent runtime.

## 2) Human Decision Boundary

- Ops Agent can investigate, score, recommend, and draft rules.
- Final fraud disposition and final rule activation are always human-controlled.

## 3) Data Ownership and Schema

- Ops Agent writes only `ops_agent_*` tables.
- TM-owned `fraud_gov` transactional data is read-only from this service perspective.

## 4) Redaction and Prompt Safety

- LLM inputs use redacted payloads.
- Stable pseudonymous identifiers are allowed for correlation (for example hashed/tokenized IDs).
- Direct sensitive personal fields are blocked from model prompts.

## 5) Rule Governance Handoff

- Agent outputs rule drafts for maker-checker workflow.
- No autonomous rule activation from ops-agent.

## 6) Rollout and SLO Gating

- Release progression must pass defined rollout gates and SLO thresholds.
- KPI-gated E2E validation is required before promotion.

## 7) ADR Policy for This Repo

- New ADR files are created only for decisions that are both:
  - cross-cutting (affect multiple modules/repos), and
  - long-lived (expected to survive routine refactors).
- Avoid one-file ADR stubs that duplicate existing docs without new decision content.
