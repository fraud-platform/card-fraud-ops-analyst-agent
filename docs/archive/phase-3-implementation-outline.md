# Card Fraud Ops Analyst Agent - Phase 3 Implementation Outline

## Planning Status

**This is a lightweight outline, not a detailed implementation plan.**

Detailed step-by-step planning will happen after Phase 2 is implemented. Reasons:

1. **Phase 3 introduces LLM reasoning on top of Phase 1+2's deterministic pipeline** — the `reasoning_engine.py` stub (currently returns `None`) needs the full pipeline context to be meaningful.
2. **Provider abstraction design depends on Phase 2's pipeline shape** — prompt payload construction needs the exact evidence structures from the completed deterministic + draft pipeline.
3. **Prompt governance and redaction policies require real evidence payloads** — cannot finalize allowlists and redaction rules until we have production-like evidence flowing.
4. **Pilot gating and SLO targets require Phase 2 baseline metrics** — need deterministic-only performance numbers before setting hybrid targets.

---

## Objectives

- Enable bounded LLM reasoning on top of deterministic evidence.
- Implement dual provider abstraction (cloud default, local fallback).
- Enforce prompt governance and redaction policy.
- Add consistency checks between deterministic evidence and LLM narrative.
- Run controlled pilot and meet operational KPIs/SLOs.
- Complete production hardening.

## Release Gates

- **Gate 4**: Performance/reliability SLOs met, runbooks/dashboards complete, dependency failure handling validated.
- **Gate 5**: KPI baselines defined, rollback plan signed off, cross-repo owner approvals.

---

## Scope by Repository

### `card-fraud-ops-analyst-agent`

| Area | What Changes |
|------|-------------|
| `reasoning_engine.py` | Replace `None` stub with LLM reasoning orchestration |
| `app/agents/reasoning_core.py` (NEW) | PURE: prompt assembly, response parsing, consistency checks |
| `app/llm/` (NEW package) | Provider abstraction, cloud client, local client, prompt templates |
| `app/llm/provider.py` | Abstract base + cloud/local implementations |
| `app/llm/prompts/` | Versioned prompt templates with schema validation |
| `app/llm/redaction.py` | Pre-call redaction/pseudonymization, allowlist enforcement |
| `app/llm/consistency.py` | Post-call checks: hallucination detection, evidence alignment |
| `pipeline.py` | Wire reasoning stage into pipeline (step 5 becomes real) |
| `config.py` | `LLMConfig` settings become active (provider, model, API keys, timeouts) |
| Feature flags | `OPS_AGENT_ENABLE_LLM_REASONING` controls hybrid vs deterministic-only |
| Fallback logic | If LLM fails, pipeline completes with deterministic-only result |
| `app/graph/` | LangGraph orchestration if conditional branching is needed |

### `card-fraud-intelligence-portal`

| Area | What Changes |
|------|-------------|
| UI labeling | Clear distinction between deterministic evidence and LLM-generated narrative |
| Feedback capture | Analyst feedback on recommendation quality (thumbs up/down, comments) |
| Model mode indicator | Badge showing `deterministic` vs `hybrid` per insight |

### `card-fraud-platform`

| Area | What Changes |
|------|-------------|
| Feature flags | Environment-specific LLM rollout toggles and kill switches |
| Secrets | LLM provider API keys via Doppler |
| Pilot gating | Controls for tenant/severity/queue segment targeting |

---

## Key New Files (Estimated)

```
app/llm/
├── __init__.py
├── provider.py              # LLMProvider ABC + CloudProvider + LocalProvider
├── prompts/
│   ├── __init__.py
│   ├── investigation_v1.py  # Prompt template for investigation reasoning
│   └── templates.py         # Template registry and versioning
├── redaction.py             # PII redaction, field allowlists
└── consistency.py           # Hallucination checks, evidence alignment

app/agents/reasoning_core.py # PURE: prompt assembly, response parsing
app/graph/orchestrator.py    # LangGraph state machine (if needed)
```

## Key Design Questions (To Resolve During Detailed Planning)

1. **Provider interface** — What's the minimal abstraction? `async def complete(prompt: str, **kwargs) -> str`? Or structured input/output?
2. **Prompt template versioning** — How to version and roll back prompt templates in production?
3. **Consistency check thresholds** — What constitutes a "hallucination" when comparing LLM narrative to deterministic evidence?
4. **Fallback behavior** — On LLM failure, return deterministic-only silently or flag to analyst?
5. **Pilot segmentation** — By tenant, severity level, queue segment, or percentage-based?
6. **LangGraph necessity** — Is the pipeline complex enough to justify LangGraph, or does the simple async function with conditional branches suffice?
7. **Local model selection** — Which local model (Ollama/vLLM) and what regression testing process for model upgrades?

## Estimated Tests

- Unit: Prompt assembly, redaction enforcement, consistency checks, provider fallback
- Integration: End-to-end with mock LLM provider, audit trail for LLM calls
- Smoke: Hybrid investigation returns both evidence and narrative
- Pilot: Controlled subset with KPI measurement against deterministic baseline
- Regression: Model change validation suite

## Pilot Promotion Criteria

Per ADR-0008 and release gates:
- Analyst throughput improvement measurable
- True positive handling quality lift
- Stable false-positive behavior (no regression)
- All Gate 4 + Gate 5 criteria met before full production rollout
