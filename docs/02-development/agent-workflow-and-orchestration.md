# Agent Workflow and Orchestration

## Fraud Analyst Workflow Alignment

### Analyst reality

- Analysts triage a queue.
- Analysts validate evidence, not just scores.
- Analysts decide and document actions.
- Rule changes require governance flow.

### Ops Agent support model

- Prepares evidence and recommendations.
- Reduces context assembly time.
- Suggests next-best actions.
- Prepares draft rule packages for human review.

## End-to-End Flows

### Flow A: Continuous triage

1. Candidate transactions selected from TM review queue.
2. Evidence-first analysis computed.
3. Optional LLM reasoning produces concise narrative.
4. Recommendation queue updated in `ops_agent_recommendations`.
5. Portal displays queue for analyst action.

### Flow B: On-demand deep investigation

1. Analyst opens transaction/case and requests deep run.
2. Agent computes enriched context and evidence.
3. Agent returns full bundle and stores run artifact.
4. Analyst acknowledges, rejects, or escalates recommendation.

### Flow C: Rule draft handoff

1. Analyst accepts recommendation with rule candidate.
2. Agent creates normalized draft package.
3. Draft package exported to Rule Management draft endpoint.
4. Maker-checker process in Rule Management owns final approval.

## Orchestration Rules

- Context/pattern/similarity stages must complete before reasoning stage.
- If LLM stage fails, rule-sequence fallback recommendation remains available.
- Every state transition must be persisted and auditable.
