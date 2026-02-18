# Phase 2 + Phase 3 Implementation Plan

## Status

| Phase | Status | Tests | Last updated |
|-------|--------|-------|--------------|
| Phase 1 — Foundation & Deterministic Core | ✅ COMPLETE | Passing (see latest quality gate run) | 2026-02-16 |
| Phase 2 — Analyst Actions & Rule Draft Handoff | ✅ COMPLETE | Passing (see latest quality gate run) | 2026-02-16 |
| Phase 3 — LLM-Hybrid Enablement | ✅ COMPLETE | Passing (see latest quality gate run) | 2026-02-16 |
| Integration — Platform + E2E wiring | ✅ COMPLETE | — | 2026-02-14 |

**Quality gates (as of 2026-02-16):** lint/format clean; required unit/smoke suites passing.

### Post-implementation fixes applied (2026-02-14)
- Schema mismatch: `rule_draft_service.py` now returns dicts matching `RuleDraftResponse` in all branches
- Evidence payload: `rule_draft_core._build_conditions_from_evidence()` reads from nested `evidence_payload` dict
- `_build_thresholds_from_evidence()` same fix applied consistently
- LLM config: removed conflicting `model` field from `LLMConfig`; `provider` (LiteLLM format) is the single source of truth
- Security validation: `validate_security_settings` logic corrected — now raises when `enforce_human_approval=False` in prod
- Outdated docstring in `pipeline._llm_reasoning()` updated

### Pending (not in this repo)
- `card-fraud-rule-management`: ingest endpoint for ops-agent draft packages (Phase 2 cross-repo, intentionally deferred)
- `card-fraud-intelligence-portal`: analyst action UI panels (Phase 2/3 cross-repo)
- Live LLM API key in Doppler for hybrid mode (`OPS_AGENT_ENABLE_LLM_REASONING=true`)

---

## Context

Phase 1 (Foundation and Deterministic Core) is **COMPLETE** — all 13 steps implemented, with clean lint/format gates and passing unit/smoke suites. The deterministic investigation pipeline works end-to-end: context building, pattern analysis, similarity analysis, recommendation generation, and audit logging.

**Both phases are now complete:**
- **Phase 2** — Rule draft core/engine/service fully implemented. Status transitions enforced (OPEN→ACKNOWLEDGED/REJECTED, ACKNOWLEDGED→EXPORTED). RM HTTP client ready, feature-flagged off (`OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT=false`).
- **Phase 3** — LiteLLM provider, prompt templates, redaction, consistency checks, and reasoning engine all implemented. Default-on (`OPS_AGENT_ENABLE_LLM_REASONING=true`). Graceful fallback to deterministic on any LLM error.

**Decisions confirmed:**
- Export transport: Direct HTTP call to RM via httpx with tenacity retry (3 attempts, exponential backoff)
- LLM provider: LiteLLM (`anthropic/claude-sonnet-4-5-20250929` default, `ollama/llama3.2` fallback)
- Scope: Ops-agent only; RM HTTP call available but export feature-flagged off pending RM ingest endpoint
- Cross-repo: RM ingest endpoint deferred to separate card-fraud-rule-management work item

---

## Phase 2 — Analyst Actions and Rule Draft Handoff

### Step 2.1 — Rule Draft Core (Pure Logic)

**New file:** `app/agents/rule_draft_core.py`

Pure functions with zero DB access (following core/adapter pattern from Phase 1):

- `@dataclass(frozen=True) RuleDraftPayload` — Normalized rule draft structure:
  - `rule_name`, `rule_description`, `conditions` (list of `RuleCondition`), `thresholds` (dict), `metadata` (provenance: recommendation_id, insight_id, source="ops-agent")
- `@dataclass(frozen=True) RuleCondition` — `field_name`, `operator`, `value`, `logical_op`
- `assemble_draft_payload(recommendation: dict, insight: dict, evidence: list[dict]) -> RuleDraftPayload` — Transforms recommendation + evidence into normalized draft
- `validate_draft_payload(payload: RuleDraftPayload) -> list[str]` — Returns validation errors (empty = valid)
- Policy: Only `rule_candidate` type recommendations can produce drafts

**Reuses:** `app/agents/recommendation_engine_core.py` pattern (frozen dataclasses, pure functions)

### Step 2.2 — Rule Draft Engine (DB-Bound Adapter)

**Modify:** `app/agents/rule_draft_engine.py` (replace stub)

- `create_draft(recommendation_id, package_version, dry_run)` → Calls `rule_draft_core.assemble_draft_payload()`, persists via `rule_draft_repo.create()`, emits audit event
- `dry_run=True` returns payload without persisting
- Validates recommendation exists, status is ACKNOWLEDGED, and type is `rule_candidate`

**Reuses:** `app/agents/recommendation_engine.py` pattern (session-based, calls core, persists via repo)

### Step 2.3 — Recommendation Status Transition Enforcement

**Modify:** `app/services/recommendation_service.py`

- Add status transition matrix:
  ```
  OPEN -> ACKNOWLEDGED (via acknowledge action)
  OPEN -> REJECTED (via reject action)
  ACKNOWLEDGED -> EXPORTED (via successful draft export)
  ```
- No backward transitions (REJECTED is terminal, EXPORTED is terminal)

**Modify:** `app/persistence/recommendation_repository.py`
- Add `update_status_with_guard()` — checks current status in WHERE clause to prevent race conditions:
  ```sql
  UPDATE ... SET status = :new_status WHERE recommendation_id = :id AND status = :expected_status
  ```

### Step 2.4 — Rule Draft Service (Full Implementation)

**Modify:** `app/services/rule_draft_service.py` (replace stubs)

- `create_draft(recommendation_id, package_version, dry_run)`:
  1. Fetch recommendation (must exist, must be ACKNOWLEDGED, must be `rule_candidate`)
  2. Fetch related insight + evidence
  3. Call `rule_draft_core.assemble_draft_payload()`
  4. Call `rule_draft_core.validate_draft_payload()`
  5. If `dry_run=True`: return payload without persisting
  6. Persist via `rule_draft_repo.create()`
  7. Emit audit event
  8. Return `RuleDraftResponse`

- `export_draft(rule_draft_id, target, target_endpoint)`:
  1. Fetch draft (must exist, export_status must be NOT_EXPORTED)
  2. Check feature flag `OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT` is enabled
  3. Call RM endpoint via `RuleManagementClient`
  4. On success: update export_status to EXPORTED, update recommendation status to EXPORTED
  5. On failure: update export_status to FAILED, emit audit with error details
  6. Emit audit event for export action

### Step 2.5 — Rule Management HTTP Client

**New file:** `app/clients/rule_management_client.py`

- `RuleManagementClient` — async httpx client for calling RM API
- `export_draft(endpoint, payload) -> ExportResult` — POST to RM with retry (tenacity, 3 retries, exponential backoff)
- Uses `settings.features.enable_rule_draft_export` guard
- Includes service-to-service auth via M2M token
- Returns structured `ExportResult(success, response_id, error_message)`

**New file:** `app/clients/__init__.py`

### Step 2.6 — Schema Updates

**Modify:** `app/schemas/v1/rule_drafts.py`
- Add `RuleDraftPayloadSchema` — Pydantic model matching `RuleDraftPayload` dataclass
- Add `RuleConditionSchema` — Pydantic model for conditions
- Update `RuleDraftResponse` — include `validation_errors` field for dry_run, `export_error` field

**Modify:** `app/schemas/v1/common.py`
- Add `ExportStatus.PENDING` if needed for in-flight exports

### Step 2.7 — Feature Flag Wiring

**Modify:** `app/core/config.py`
- `FeatureFlagsConfig.enable_rule_draft_export` already exists (default=False)
- Add `rule_management_base_url: str = ""` to config for RM endpoint discovery

**Doppler:** Add `RULE_MANAGEMENT_BASE_URL` secret (value: `http://rule-management:8000/api/v1` for local)

### Step 2.8 — Audit Trail Completeness

**Modify:** `app/services/audit_service.py` / `app/agents/audit_engine.py`
- Ensure all Phase 2 mutations emit audit events:
  - `recommendation:status_change:acknowledged`
  - `recommendation:status_change:rejected`
  - `recommendation:status_change:exported`
  - `rule_draft:created`
  - `rule_draft:export:success`
  - `rule_draft:export:failed`
  - `rule_draft:validated` (dry_run)

### Step 2.9 — Phase 2 Tests

**New file:** `tests/unit/test_rule_draft_core.py`
- Draft assembly from recommendation + evidence
- Validation: missing fields, invalid conditions, non-rule_candidate type
- Determinism: same input -> same output

**New file:** `tests/unit/test_rule_draft_service.py`
- Mock DB: create draft, export draft, dry_run
- Status transition guards (only ACKNOWLEDGED -> can create draft)
- Feature flag enforcement

**New file:** `tests/unit/test_recommendation_status_transitions.py`
- Valid transitions: OPEN->ACKNOWLEDGED, OPEN->REJECTED, ACKNOWLEDGED->EXPORTED
- Invalid transitions: REJECTED->anything, EXPORTED->anything, OPEN->EXPORTED

**New file:** `tests/unit/test_rule_management_client.py`
- Mock httpx: success, retry on 5xx, failure handling

**Modify:** `tests/smoke/test_api_smoke.py`
- Add smoke tests for rule draft endpoints (201 on create, 200 on export)

**Estimated new tests:** ~40 unit tests

### Step 2.10 — Phase 2 Gate Verification

Gate 2 (Security and Data Governance):
- Scope-based authz tests pass (ops_agent:draft required)
- Audit immutability checks pass (all mutations logged)

Gate 3 (Analyst UX Validation):
- Acknowledge/reject flow works
- Draft creation from accepted recommendation works
- Export to RM succeeds (mocked)
- Human final review checkpoints visible (status transitions enforced)

---

## Phase 3 — LLM-Hybrid Enablement

### Step 3.1 — LiteLLM Provider Abstraction

**New package:** `app/llm/`

**New file:** `app/llm/__init__.py`

**New file:** `app/llm/provider.py`
- `LLMProvider` — ABC with `async def complete(messages: list[dict], **kwargs) -> LLMResponse`
- `LLMResponse` dataclass: `content: str`, `model: str`, `usage: dict`, `latency_ms: float`
- `LiteLLMProvider(LLMProvider)` — wraps `litellm.acompletion()` for provider-agnostic calls
  - Supports: `anthropic/claude-sonnet-4-5-20250929`, `gpt-4o-mini`, `ollama/llama3.2`, etc.
  - Configurable via `LLMConfig` (provider, model, api_key, base_url, timeout)
- `get_llm_provider(settings: Settings) -> LLMProvider` — factory function

### Step 3.2 — Prompt Templates and Governance

**New file:** `app/llm/prompts/__init__.py`

**New file:** `app/llm/prompts/templates.py`
- `PromptTemplate` dataclass: `name`, `version`, `system_prompt`, `user_template`
- `PromptRegistry` — versioned template store, lookup by name+version
- Templates stored as Python constants (not files), versioned by string

**New file:** `app/llm/prompts/investigation_v1.py`
- System prompt: fraud analyst role, bounded reasoning, must reference evidence
- User template: structured evidence payload placeholder
- Output format: JSON with `narrative`, `risk_assessment`, `key_findings`, `confidence`

### Step 3.3 — Redaction and Allowlist

**New file:** `app/llm/redaction.py`
- `RedactionPolicy` — defines allowed fields for LLM context (allowlist approach)
- `redact_context(context: dict, policy: RedactionPolicy) -> dict` — strips disallowed fields
- Allowed: pseudonymized IDs (hashed card, merchant ID, device hash), amounts, timestamps, pattern scores, similarity scores
- Blocked: raw PAN, cardholder name, address, phone, email, IP address
- `validate_prompt_payload(payload: dict, policy: RedactionPolicy) -> list[str]` — returns violations
- Per ADR-0005: stable pseudonymous identifiers allowed, direct PII blocked

### Step 3.4 — Consistency Checks

**New file:** `app/llm/consistency.py`
- `check_consistency(llm_response: dict, deterministic_evidence: dict) -> ConsistencyResult`
- Checks:
  - Severity alignment: LLM-stated severity matches deterministic severity (+/- 1 level)
  - Evidence grounding: LLM narrative references at least N% of deterministic evidence items
  - No fabrication: LLM doesn't reference transaction IDs or merchants not in evidence
  - Confidence calibration: LLM confidence roughly aligns with pattern scores
- `ConsistencyResult` dataclass: `passed: bool`, `violations: list[str]`, `score: float`
- On failure: flag to analyst, log for review, optionally fall back to deterministic-only

### Step 3.5 — Reasoning Engine (Full Implementation)

**New file:** `app/agents/reasoning_core.py`
- PURE functions (zero DB, zero LLM calls):
- `assemble_prompt_payload(context, pattern_analysis, similarity_analysis) -> dict` — structured evidence for prompt template
- `parse_llm_response(raw_response: str) -> dict` — JSON parse with fallback
- `merge_reasoning_with_evidence(reasoning: dict, deterministic: dict) -> dict` — combine LLM narrative with deterministic evidence

**Modify:** `app/agents/reasoning_engine.py` (replace stub)
- `reason(context, pattern_analysis, similarity_analysis) -> dict | None`:
  1. Check feature flag `OPS_AGENT_ENABLE_LLM_REASONING` — if disabled, return None (deterministic-only)
  2. Call `reasoning_core.assemble_prompt_payload()`
  3. Apply `redaction.redact_context()` to payload
  4. Validate with `redaction.validate_prompt_payload()`
  5. Load prompt template from registry
  6. Call `llm_provider.complete()` with timeout
  7. Parse response via `reasoning_core.parse_llm_response()`
  8. Run `consistency.check_consistency()`
  9. If consistency fails: log, return None (fallback to deterministic)
  10. Return merged reasoning result
  11. On any LLM error: log, return None (graceful fallback)

### Step 3.6 — Pipeline Integration

**Modify:** `app/agents/pipeline.py`
- Wire reasoning result into recommendation generation:
  ```python
  reasoning_result = await self._llm_reasoning(context, pattern_analysis, similarity_analysis)
  recommendation_result = await self._recommendation_generation(
      context, pattern_analysis, similarity_analysis, transaction_id, reasoning=reasoning_result
  )
  ```
- Add `model_mode` field to pipeline output: `"deterministic"` if reasoning is None, `"hybrid"` otherwise
- Add OTel span attributes for LLM latency, model used, consistency score

**Modify:** `app/agents/recommendation_engine.py`
- Accept optional `reasoning` parameter
- If reasoning provided, enhance insight summary with LLM narrative
- Store `model_mode = "hybrid"` on insight record

### Step 3.7 — Config and Feature Flags

**Modify:** `app/core/config.py`
- Update `LLMConfig`:
  - `provider: str = "anthropic/claude-sonnet-4-5-20250929"` (LiteLLM format)
  - Add `fallback_model: str = "ollama/llama3.2"` for local fallback
  - Add `prompt_guard_enabled: bool = True`
  - Add `max_prompt_tokens: int = 4000`
  - Add `consistency_threshold: float = 0.7`

**Doppler:** Add secrets:
- `LLM_API_KEY` (Anthropic API key)
- `LLM_PROVIDER` (default: `anthropic/claude-sonnet-4-5-20250929`)
- `LLM_FALLBACK_MODEL` (default: `ollama/llama3.2`)

### Step 3.8 — Dependencies Update

**Modify:** `pyproject.toml`
- Add `litellm>=1.50` to dependencies
- Add `tenacity>=8.2` if not already present (for RM client retries)

### Step 3.9 — Phase 3 Tests

**New file:** `tests/unit/test_reasoning_core.py`
- Prompt payload assembly from evidence
- Response parsing (valid JSON, invalid JSON fallback)
- Evidence merging with deterministic data

**New file:** `tests/unit/test_redaction.py`
- Allowlist enforcement: PII fields stripped
- Pseudonymized fields preserved
- Violation detection

**New file:** `tests/unit/test_consistency.py`
- Severity alignment checks
- Evidence grounding checks
- Fabrication detection

**New file:** `tests/unit/test_llm_provider.py`
- LiteLLM provider with mock responses
- Timeout handling
- Fallback behavior

**New file:** `tests/unit/test_prompt_templates.py`
- Template registry lookup
- Template rendering with evidence payload
- Version management

**Modify:** `tests/smoke/test_api_smoke.py`
- Add smoke test: investigation with `OPS_AGENT_ENABLE_LLM_REASONING=false` returns deterministic-only
- Verify model_mode field in response

**Estimated new tests:** ~50 unit tests

### Step 3.10 — Phase 3 Gate Verification

Gate 4 (Pilot Readiness):
- Performance SLOs: quick investigation P95 <= 2s (deterministic), P95 <= 5s (hybrid)
- Fallback validated: LLM failure -> deterministic-only response
- Redaction policy enforced in all prompt payloads
- Consistency checks catch fabricated evidence

Gate 5 (Production Enablement):
- KPI baselines defined (analyst throughput, true positive quality)
- Rollback: `OPS_AGENT_ENABLE_LLM_REASONING=false` kills LLM reasoning instantly
- Runbooks updated for LLM incidents

---

## Implementation Order (Combined)

| Step | Description | Files Modified/Created | Est. Tests |
|------|-------------|----------------------|------------|
| **Phase 2** | | | |
| 2.1 | Rule draft core (pure logic) | `app/agents/rule_draft_core.py` (NEW) | 10 |
| 2.2 | Rule draft engine (adapter) | `app/agents/rule_draft_engine.py` | 5 |
| 2.3 | Recommendation status transitions | `app/services/recommendation_service.py`, `app/persistence/recommendation_repository.py` | 8 |
| 2.4 | Rule draft service (full) | `app/services/rule_draft_service.py` | 8 |
| 2.5 | RM HTTP client | `app/clients/rule_management_client.py` (NEW), `app/clients/__init__.py` (NEW) | 5 |
| 2.6 | Schema updates | `app/schemas/v1/rule_drafts.py`, `app/schemas/v1/common.py` | 2 |
| 2.7 | Feature flag wiring | `app/core/config.py` | 0 |
| 2.8 | Audit trail | `app/services/audit_service.py` | 2 |
| 2.9 | Phase 2 tests | `tests/unit/test_rule_draft_*.py` (NEW), smoke updates | ~40 |
| 2.10 | Gate 2+3 verification | Manual verification | 0 |
| **Phase 3** | | | |
| 3.1 | LiteLLM provider | `app/llm/provider.py` (NEW) | 5 |
| 3.2 | Prompt templates | `app/llm/prompts/` (NEW) | 5 |
| 3.3 | Redaction/allowlist | `app/llm/redaction.py` (NEW) | 8 |
| 3.4 | Consistency checks | `app/llm/consistency.py` (NEW) | 8 |
| 3.5 | Reasoning engine (full) | `app/agents/reasoning_core.py` (NEW), `app/agents/reasoning_engine.py` | 10 |
| 3.6 | Pipeline integration | `app/agents/pipeline.py`, `app/agents/recommendation_engine.py` | 5 |
| 3.7 | Config updates | `app/core/config.py` | 2 |
| 3.8 | Dependencies | `pyproject.toml` | 0 |
| 3.9 | Phase 3 tests | `tests/unit/test_reasoning_*.py` (NEW), `tests/unit/test_redaction.py` (NEW), etc. | ~50 |
| 3.10 | Gate 4+5 verification | Manual verification | 0 |

**Total estimated new tests:** ~90 (bringing total from 132 to ~222)

---

## Verification Results

### Phase 2 + Phase 3 gates — PASSED (2026-02-14)
```
✓ Lint:    0 errors  (uv run ruff check app/ tests/ cli/ scripts/)
✓ Format:  clean  (uv run ruff format --check ...)
✓ Unit:    passing  (uv run pytest tests/unit -v)
✓ Smoke:   passing   (uv run pytest tests/smoke -v)
Total:     required suites passing

Integration gate status (same date):
- `tests/integration/test_database_integration.py` added (DB connectivity + ops_agent table presence)
- Latest local validation run on 2026-02-18: 2 passed, 0 skipped
  (`doppler run --config local -- uv run pytest tests/integration -v`).
- If Doppler `local-test` is unavailable in your workspace, use `local` for integration runs.
```

### Integration + E2E wiring — COMPLETE (2026-02-14)
- `card-fraud-platform/docker-compose.apps.yml` — `ops-analyst-agent` service added (port 8003, `apps` profile)
- `card-fraud-e2e-load-testing` — `OpsAnalystUser`, `OpsAnalystConfig`, `InvestigationTaskset`, `WorklistTaskset` added; toggle via `TEST_OPS_ANALYST=true`
- `scripts/load_test_data.py` — Idempotent seed script (10 transactions + ops_agent_* rows); CLI: `uv run db-load-test-data`

---

## Governance Reminders

- **No shortcuts** — every stub replaced, every test written
- **uv only** — never pip
- **Doppler only** — no .env files
- **Database isolation** — only `ops_agent_*` tables touched
- **Human final authority** — no automatic rule activation
- **Deviation from plan requires explicit human approval**
- **Quality gates must ALL pass** before each phase is considered complete
