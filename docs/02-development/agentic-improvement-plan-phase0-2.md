# Agentic Improvement Plan (Phase 0/1/2)

Updated: 2026-02-27

This document is a repo-by-repo execution plan to increase agent autonomy and investigation quality while preserving human-in-loop controls.

It also fixes a critical testing/reporting issue: the current detailed HTML report can show **PASS** even when internal tool steps fail (for example `embedding_or_similarity_failed`), because the report pass/fail is primarily driven by HTTP status codes recorded in stages, not investigation-quality KPIs.

Reference example: `docs/temporary-reports/e2e-scenarios-report-31matrix-20260226-081447.html` shows `Passed=31` while containing repeated internal errors like `"reason": "embedding_or_similarity_failed"` and `"error": "All connection attempts failed"`.

## Goals

- Make E2E runs deterministic at the infrastructure layer (no stale containers, no missing dependencies).
- Make E2E reporting **truthful** (green only when the investigation result is healthy and useful).
- Improve agent reasoning quality via deterministic feature extraction (`context.features`) and evidence-cited narratives.
- Add link-analysis signals starting without a graph DB, then expand to device/IP rings once TM query support is in place.
- Align Portal UI types and rendering with `model_mode="agentic"` and new evidence sections.
- Correct rule draft export integration so ops-agent exports into Rule Management's real API contract.


## Current Status Snapshot (2026-02-27)

Completed in codebase:
- Timestamped report naming is implemented for matrix and pytest report flows.
- Docker prechecks are wired in matrix and pytest flows (`assert_local_docker_ops_agent`, `assert_local_docker_transaction_management`).
- Report metadata includes git SHA and base URLs.
- KPI computation and rendering are wired into HTML reports.
- Matrix stale-run recovery is implemented (`409` recovery + stale in-progress auto-failover).
- Context features are computed deterministically in `context.features`.
- Reasoning contract includes structured hypotheses, known/unknown facts, and evidence citations.
- Similarity path supports SQL heuristic fallback when embedding calls fail.

Fixed in this pass:
- KPI evaluation is now rendered as a dedicated scenario so report status is explicit.
- Matrix command now exits non-zero when KPI gate fails.
- Stage-audit output is generated after final scenario status adjustments (no stale pass/fail drift).
- 31-matrix run is clean and KPI-gated (`kpi_all_pass=True`) in `htmlcov/e2e-31matrix-report-20260227-162414.html`.
- 23-scenario pytest E2E suite is clean (`23 passed`) in `htmlcov/e2e-pytest-report-20260227-163202.html`.

Still pending:
- Full trace usability hardening in Jaeger (search by investigation id end-to-end).
- Rule export contract alignment with Rule Management API.
- Cross-repo portal/UI model mode cleanup in `card-fraud-intelligence-portal`.

## Non-Goals (for Phase 0-2)

- Fully automated fraud decisions (human control remains final).
- Automatic rule activation (maker-checker remains required).
- Training a bespoke model (focus is tool+context+prompt+feedback loop first).

## Phase 0 (Prereq): Reliability + Truthful E2E + Usable Tracing

### Outcomes

- The 31-scenario E2E matrix fails only for real regressions (not environment drift).
- The HTML report header `Passed/Failed` matches investigation-quality KPIs (no false green).
- Jaeger traces are searchable by `investigation_id` and show tool/node spans with attributes.

### Repo: `card-fraud-ops-analyst-agent` (this repo)

#### 0.1 Fix E2E dependency readiness contract

Problem pattern:
- Context failures like `[Errno -2] Name or service not known` occur when ops-agent runs in Docker but TM is not reachable via the Docker network hostname.

Touch points:
- `scripts/docker_guard.py`
  - Ensure it verifies both:
    - ops-agent container publishes `8003`
    - Transaction Management container is up and reachable
- `scripts/run_e2e_matrix_detailed.py`
  - Already imports `assert_local_docker_ops_agent` and `assert_local_docker_transaction_management`
  - Enforce these assertions before the matrix begins.
- `app/core/config.py`
  - Container rewrite of `TMClientConfig.base_url` to `http://transaction-management:...` is correct, but E2E must guarantee TM is up.

Acceptance:
- If TM is not reachable, E2E fails fast before running scenarios, with a single clear error.

#### 0.2 Make matrix report "truthful" (no false green)

Problem pattern:
- `tests/e2e/reporter.py` marks a stage passed when `status == 200`.
- The matrix runner (`scripts/run_e2e_matrix_detailed.py`) records stages as passed whenever the HTTP response is 200, even if response bodies contain internal tool failures or degraded outputs.

Touch points:
- `scripts/run_e2e_matrix_detailed.py`
  - Add scenario-level issue detection that parses investigation detail for:
    - `tool_executions[*].status == "FAILED"` or non-empty `error_message`
    - response fields indicating degraded similarity/embedding (for example `reason=embedding_or_similarity_failed`)
    - missing mandatory context fields for the scenario class (see Phase 0.3 KPI gate)
  - If any blocking issue exists, mark the scenario as failed in the report output.
- `tests/e2e/reporter.py`
  - Option A: keep stage status as HTTP-derived, but render a scenario badge as FAIL if KPI gate fails.
  - Option B: set stage status to non-200 when KPI gate fails at the "Validate Expectations" stage.

Acceptance:
- A report cannot show `Passed=31` if similarity/embedding failed or context is empty.

#### 0.3 Add measurable KPI gate (report + CI-friendly JSON)

Implement a single "Evaluate Acceptance KPIs" stage appended at end of matrix run.

Touch points:
- `scripts/run_e2e_matrix_detailed.py`
  - Compute KPI metrics from all scenario rows and write into the report JSON.
  - Record a final stage in reporter with `response_body={"kpis": ...}` so HTML shows the KPI cards (this is already supported by `tests/e2e/reporter.py` via `_extract_acceptance_kpis()`).
- `tests/e2e/reporter.py`
  - No changes required for KPI rendering; it already renders KPI cards when a stage named `Evaluate Acceptance KPIs` exists.

Proposed KPIs (targets for local/dev):
- `kpi_e2e_scenarios_pass_rate`
  - value: passed_scenarios / total_scenarios
  - target: `1.0` (must be 100% for merge)
- `kpi_context_completeness_rate`
  - value: scenarios where context has non-null `transaction_id`, `amount`, `currency`, `card_id`, `merchant_id`, `decision`
  - target: `>= 0.99`
- `kpi_tool_failure_rate`
  - value: scenarios where any `tool_executions[*].status == FAILED`
  - target: `0.0`
- `kpi_similarity_degraded_rate`
  - value: scenarios with similarity evidence containing `reason=embedding_or_similarity_failed` (or equivalent)
  - target: `0.0`
- `kpi_reasoning_fallback_rate`
  - value: scenarios where reasoning summary contains fallback markers like "No transaction data provided" when context is present
  - target: `<= 0.02`
- `kpi_latency_p95_investigation_ms`
  - value: P95 time from `POST /investigations/run` to terminal status
  - target: define a local baseline and reduce over time; initial gate: `< 60000` (60s)
- `kpi_trace_coverage_rate`
  - value: scenarios whose investigation details include a trace identifier (for example `trace_id` or `otel.trace_id`)
  - target: `>= 0.95`

#### 0.4 Unify report filenames to avoid accidental publishing of stale/misleading outputs

Problem pattern:
- Both pytest (`tests/e2e/test_scenarios.py`) and matrix runner (`scripts/run_e2e_matrix_detailed.py`) default to writing `htmlcov/e2e-scenarios-report.html`.

Touch points:
- `tests/e2e/test_scenarios.py`
  - Change `REPORT_PATH` to a timestamped name or include a suffix `-pytest`.
- `scripts/run_e2e_matrix_detailed.py`
  - Default HTML report path should be timestamped or include `-31matrix`.
  - Optionally write a small `htmlcov/latest-e2e-report.html` redirect file.

Acceptance:
- "Which run produced this report?" is answerable from filename + report metadata (also include git SHA and timestamp in the report body).

#### 0.5 Jaeger traces become searchable and meaningful

Touch points:
- `app/main.py` (OpenTelemetry initialization and FastAPI instrumentation)
- `app/agent/planner.py`, `app/agent/executor.py`, `app/agent/completion.py`
- `app/tools/*_tool.py` (span attributes per tool execution)
- `docs/06-operations/observability.md` (update troubleshooting and search instructions)

Implementation notes:
- Add span attributes:
  - `investigation_id`
  - `transaction_id`
  - `tool_name`
  - `tool_status`
  - `model_mode`
  - `scenario_name` (when E2E sets one via header)

Acceptance:
- In Jaeger (`http://localhost:16686`), you can search by `investigation_id` and see a single trace with tool spans.

### Repo: `card-fraud-platform` (compose orchestration)

Touch points:
- `docker-compose.apps.yml`
  - Validate that the "apps" profile brings up both `transaction-management` and `ops-analyst-agent` when requested for e2e runs.
- `AGENTS.md` (platform) and/or runbook docs
  - Ensure the recommended E2E command starts dependencies, not just ops-agent alone.

Acceptance:
- "One command" starts everything required for a clean local E2E run.

## Phase 1: Context Features + Strong Reasoning Contract (No New Infra)

### Outcomes

- Investigation outputs contain deterministic `context.features` that tools and prompts can rely on.
- Reasoning cites evidence and does not degrade into generic summaries when data exists.
- Latency improves through caching and fewer repeated TM calls.

### Repo: `card-fraud-ops-analyst-agent`

#### 1.1 Add deterministic `context.features`

Approach:
- Add a new tool/node: `ContextFeaturesTool` that runs immediately after `ContextTool`.
- This tool consumes raw TM payload (overview + histories) and produces a stable feature pack.

Touch points:
- `app/tools/context_tool.py` (raw TM fetch remains here)
- `app/tools/_core/context_logic.py` (extend or add `features` assembly)
- Add new:
  - `app/tools/context_features_tool.py`
  - `app/tools/_core/context_features_logic.py`
- `app/services/investigation_service.py` graph registry
  - register the new tool and update graph wiring

Feature set v1 (derived without new dependencies):
- Core fields: `transaction_id`, `amount`, `currency`, `decision`, `mcc`, `timestamp`, `card_id`, `merchant_id`
- Window stats (card and merchant):
  - `txn_count_5m`, `txn_count_1h`, `txn_count_24h`
  - `decline_rate_1h`, `avg_amount_30d`, `amount_zscore`
  - `distinct_merchants_1h`, `distinct_cards_1h`
- Engine artifacts passthrough:
  - `transaction_context`, `velocity_snapshot`, `velocity_results`, `engine_metadata`
- Network/device passthrough when available:
  - `ip_address`, `ip_country_alpha3`, `device.device_id`, `device.device_fingerprint_hash`

Acceptance:
- E2E KPI `kpi_context_completeness_rate >= 0.99` is met and the feature pack is present in investigation detail.

#### 1.2 Update reasoning contract to be evidence-cited and hypothesis-driven

Touch points:
- `app/tools/reasoning_tool.py` (prompt, output schema, validation)
- `app/tools/recommendation_tool.py` (prompt guidance that references `context.features`)
- `app/schemas/v1/investigations.py` or related schemas for reasoning payload (if needed)

Contract requirements:
- Output must contain:
  - known facts (sourced from `context.features`)
  - unknowns (explicit)
  - 2-4 hypotheses with confidence
  - citations referencing evidence/tool outputs
  - "what would change my mind" section

Acceptance:
- KPI `kpi_reasoning_fallback_rate <= 0.02` and evidence citations appear for every MEDIUM+ severity case.

#### 1.3 Reduce 31-matrix wall time without lowering quality

Touch points:
- `app/clients/tm_client.py` (or wherever TM calls are made)
  - add per-investigation caching for repeated fetches (card/merchant history)
- `app/services/investigation_service.py`
  - run independent tool calls in parallel where graph permits
- `app/core/config.py`
  - model configuration split: light planner vs heavy reasoning

Acceptance:
- KPI `kpi_latency_p95_investigation_ms` decreases relative to baseline; set baseline from first clean Phase 0 run.

### Repo: `card-fraud-intelligence-portal` (UI)

#### 1.4 Align UI types and labels with agentic API

Problem pattern:
- UI currently defines `OpsAgentModelMode = "deterministic" | "hybrid"`, but ops-agent returns `model_mode="agentic"`.

Touch points:
- `src/types/opsAnalyst.ts`
  - update `OpsAgentModelMode` to include `"agentic"`
  - verify run mode enum matches API (`"quick"`, `"deep"` or actual API values)
- `src/resources/transactions/components/OpsAnalystInsightPanel.tsx`
  - update tag rendering to show "Agentic"
- `src/mocks/handlers.ts`
  - update mock payloads and tests to reflect agentic values

Acceptance:
- UI renders the model_mode correctly and does not mislabel agentic as deterministic.

## Phase 2: Link Analysis (Start Without Graph DB, Then Expand)

### Outcomes

- Agent detects coordinated activity via link features and presents ring hypotheses with evidence.
- Phase 2A requires no new infrastructure.
- Phase 2B adds device/IP ring detection via TM query support.

### Repo: `card-fraud-ops-analyst-agent`

#### 2A Add LinkAnalysisTool using card and merchant histories only

Touch points:
- Add new:
  - `app/tools/link_analysis_tool.py`
  - `app/tools/_core/link_analysis_logic.py`
- `app/services/investigation_service.py` tool registry + graph wiring
- `app/templates/trace_viewer.py` (optional)
  - render link analysis section in the trace viewer

Signals (no graph DB):
- card fan-out: distinct merchants per card (5m/1h/24h) and burst score
- merchant fan-in: distinct cards per merchant (1h/24h) and burst score
- shape heuristics:
  - card testing signature
  - mule merchant signature
  - compromised merchant signature

Acceptance:
- For seeded scenarios that imply spread/testing, link analysis evidence is non-empty and cited by reasoning.

### Repo: `card-fraud-transaction-management` (TM)

#### 2B Add query support for IP/device neighborhoods (requires TM changes)

Ground truth:
- TM models include `ip_address` and `device` fields in `app/domain/models/transaction.py`.
- TM DB schema includes JSONB columns `transaction_context`, `velocity_snapshot`, `engine_metadata` and GIN indexes on them.

Touch points:
- API:
  - `app/api/routes/decision_events.py` and/or transaction list routes
  - add query params for `ip_address`, `device_id`, `device_fingerprint_hash`
- Persistence:
  - `app/persistence/transaction_repository.py`
  - add WHERE clause support and safe parameterization
- DB:
  - migrations or schema updates if fields are not first-class columns
  - indexes for fast lookup on new filters

Acceptance:
- TM can return "transactions sharing device/IP within window" at interactive latency for local dev-sized data.

### Repo: `card-fraud-ops-analyst-agent` (phase 2B consumer)

Touch points:
- `app/clients/tm_client.py` (new client methods)
- `app/tools/link_analysis_tool.py` (augment with device/IP neighborhood fetch)

Acceptance:
- Link analysis detects cross-card device/IP clusters in seeded/QA datasets.

## Cross-Repo Contract Fix: Rule Export Integration

### Problem

Ops-agent currently defaults to exporting to a Rule Management endpoint:
- `app/schemas/v1/rule_drafts.py` sets `target_endpoint="/api/v1/ops-agent-drafts/import"`

Rule Management actual API is:
- `POST /api/v1/rules` in `card-fraud-rule-management/app/api/routes/rules.py`

### Options

Option A (recommended):
- Change ops-agent export to call `POST /api/v1/rules` and map ops-agent draft payload into Rule Management's `RuleCreate`:
  - `rule_name`, `description`, `rule_type`, `condition_tree`, `priority`, `action`

Option B:
- Add `/api/v1/ops-agent-drafts/import` to rule-management and keep ops-agent as-is.

Touch points in ops-agent:
- `app/tools/_core/rule_draft_logic.py` (draft assembly)
- `app/clients/rule_management_client.py` (export client)
- `app/schemas/v1/rule_drafts.py` (export target contract)

Touch points in rule-management:
- `app/api/routes/rules.py`
- `app/api/schemas/rule.py` (RuleCreate schema)

Acceptance:
- Exported drafts land as DRAFT rules in rule-management and can proceed through maker-checker flow.

## Operational Guardrails (Avoid Publishing Bad Reports Again)

Add a lightweight publish gate:
- Never publish HTML reports unless:
  - `kpi_e2e_scenarios_pass_rate == 1.0`
  - `kpi_tool_failure_rate == 0.0`
  - `kpi_similarity_degraded_rate == 0.0`
- Embed metadata in report:
  - `generated_at`, `git_sha`, `base_url`, `tm_base_url`, `image_tag` (if known)

Touch points:
- `scripts/run_e2e_matrix_detailed.py`
- `tests/e2e/reporter.py` (render metadata)
- `docs/temporary-reports/README.md` (state that reports are only meaningful if KPI gate passes)

## Execution Checklist (Suggested PR Sequence)

1. PR1 (ops-agent): Phase 0.2/0.3/0.4 (truthful KPI gate + filenames + metadata)
2. PR2 (ops-agent): Phase 0.1/0.5 (dependency guard + trace attributes + Jaeger searchability)
3. PR3 (ops-agent): Phase 1.1/1.2 (context.features + reasoning contract)
4. PR4 (portal): Phase 1.4 (types/labels align to agentic)
5. PR5 (ops-agent + rule-mgmt): Rule export contract fix (Option A or B)
6. PR6 (ops-agent): Phase 2A (link analysis without TM changes)
7. PR7 (TM + ops-agent): Phase 2B (device/IP ring detection)
