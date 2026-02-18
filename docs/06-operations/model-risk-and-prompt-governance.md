# Model Risk and Prompt Governance

## Objective

Keep LLM usage bounded, explainable, and auditable in fraud operations.

## Governance Model

- Deterministic evidence is mandatory.
- LLM output is supplementary narrative and recommendation phrasing.
- No direct automated action from LLM output.

## Prompt Governance

- Prompt templates versioned.
- Allowed feature payload schema versioned.
- Prompt redaction checks enforced before provider call.
- Prompt and response metadata stored in audit-safe form.

## Model Lifecycle Controls

- Approved model list by environment.
- Change control for model upgrades.
- Regression validation before provider/model change.
- Rollback path for model regressions.

## Quality Controls

- Hallucination checks on critical fields.
- Consistency checks against deterministic evidence.
- Analyst feedback loop for recommendation quality metrics.

## Agentic Trace Controls

- Every investigation response publishes an `agentic_trace` block with stage timings and statuses (`context_build`, `pattern_analysis`, `similarity_analysis`, `llm_reasoning`, `recommendations`).
- LLM audit fields are explicit per run: `llm_status`, `llm_model`, `llm_latency_ms`, and `llm_reasoning_hash`.
- Similarity stage metadata separates vector state explicitly: `vector_feature_enabled`, `vector_stage_executed`, and `vector_match_count`.
- Run records persist `runtime_feature_flags` and `runtime_safeguards` so detail views replay the exact controls in effect at execution time (not current config).
- Actionability is explicit with `action_plan` and `evidence_gaps` to guide analyst next steps and document residual uncertainty.
