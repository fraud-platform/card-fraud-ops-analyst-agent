# E2E Test & Fraud Ops Workflow Improvement Plan

## Executive Summary

After a thorough analysis of the entire pipeline — from seed data → context builder → pattern engine → similarity engine → LLM reasoning → recommendation engine → insight persistence → E2E test validation → HTML report — I've identified **systemic gaps** that prevent the E2E tests from capturing a realistic fraud ops analyst workflow. The current output (e.g., `severity: LOW, recommendations: 1, evidence: 0`) is thin because of interconnected issues across **data seeding, pipeline configuration, test assertions, and report formatting**.

## Status Update (2026-02-18)

The following priority fixes are now implemented and validated in this repository:

- [x] Vector and LLM are default-on (`VECTOR_ENABLED=true`, `OPS_AGENT_ENABLE_LLM_REASONING=true`) and E2E preflight fails fast when vector is disabled.
- [x] Idempotent persistence for insights/recommendations now refreshes existing rows on replay (`ON CONFLICT ... DO UPDATE`) instead of silently keeping stale outputs.
- [x] Time-window feature extraction is anchored to the investigated transaction timestamp (not wall-clock `now`), preventing false LOW severity on seeded historical scenarios.
- [x] Acceptance KPI gate is active and aligned with hybrid mode runtime: `run_investigation_p95_ms <= 30000`.
- [x] Latest full scenario run passed on 2026-02-18 15:06:51 local time: 23/23 passed, 0 failed, 0 skipped (`htmlcov/e2e-scenarios-report.html`).
- [x] Acceptance KPI gate passed in the same run (`scenario_pass_rate=1.0`, `fraud_recall_medium_plus=1.0`, `low_risk_precision_low_only=1.0`).
- [x] Playwright CLI report review flow is validated for local QA.

Local execution note:
- Primary app port remains `8003` in platform mode.
- E2E must run against the Dockerized ops-agent container on `http://localhost:8003` (no alternate local port override).

---

## Root Cause Analysis

### Problem 1: Seed Data Doesn't Trigger Pattern Thresholds Reliably

**Issue:** Many seed scenarios create the *surface-level* appearance of fraud (e.g., 6 card testing transactions), but the pattern engine's scoring logic uses time-windowed queries (`compute_all_windows`) that look at card/merchant history within 1h/6h/24h/72h windows. Key problems:

- **`seed_likely_fraud`** seeds a *single* transaction with no card history → velocity score = 0, decline ratio = 0, cross-merchant = 0 → severity = LOW
- **`seed_approved_likely_fraud`** also seeds a *single* transaction with no history → same result, LOW severity
- **`seed_card_testing_sequence`** seeds 6 transactions but the *test* transaction ID is `txn_uuid` (assigned before insertion), and the final transaction is an APPROVE with a different `transaction_id` from the preceding DECLINE ones. The pattern engine queries card history by `card_id`, but the seed creates each with a unique `transaction_id` via `generate_uuid7()` — **the last transaction returned to the test may not be the one with the richest history**.

**Root cause:** `context_builder.py` queries `get_card_history(card_id, hours_back=72)` — this returns transactions for the same card. However, the pattern engine (`pattern_engine_core.py`) calculates velocity from `windows[1].transaction_count`, decline ratio from `windows[24].decline_count / windows[24].transaction_count`, and cross-merchant from `windows[24].unique_merchants`. For scenarios like `LIKELY_FRAUD` with a *single* transaction, these all compute to trivial values.

### Problem 2: Feature Flags Disable Key Pipeline Stages

**Issue:** In older `app/core/config.py` snapshots, the default feature flags were:
```python
counter_evidence_enabled: bool = Field(default=False)
conflict_matrix_enabled: bool = Field(default=False)
explanation_builder_enabled: bool = Field(default=False)
enable_llm_reasoning: bool = Field(default=True)
```

This means:
- **No conflict matrix** is computed → no conflict section in output
- **No explanation builder** runs → no human-readable markdown explanation
- **No LLM reasoning** → deterministic-only mode, which produces skeletal summaries
- **Counter-evidence** analysis is disabled → no downgrade logic for legitimate transactions

The E2E tests run against whatever the deployed environment's config is, but `SCENARIO_EXPECTATIONS` doesn't account for which features are enabled. This creates a disconnect where tests expect keywords like "counter-evidence", "downgrade", "3DS" etc. but the pipeline never generates them.

Current repository defaults are now `OPS_AGENT_ENABLE_LLM_REASONING=true` and `VECTOR_ENABLED=true`.
If either is `false`, treat it as an explicit environment override.

### Problem 3: Insight Summary Generation Is Too Skeletal

**Issue:** In `recommendation_engine.py`, `_generate_summary()` produces the deterministic insight summary. For LOW severity with no counter-evidence flags, the output is:
```
"Low fraud risk - no significant anomalous patterns detected."
```

For MEDIUM severity with indicators, it's slightly better:
```
"Moderate fraud risk indicators present: velocity burst (12 transactions in 1h)."
```

But this completely lacks:
- Transaction amount, currency, merchant info
- Card age, transaction history depth
- Rule match details from TM
- Time-of-day analysis
- Specific risk factor breakdown

A fraud ops analyst needs a **narrative** that connects evidence to conclusions.

### Problem 4: Recommendations Are Too Generic

**Issue:** `recommendation_engine_core.py` → `generate_recommendations()` generates hardcoded candidates:
- `"High-priority review required"` for HIGH/CRITICAL
- `"Create case for velocity investigation"` for velocity >= 0.6
- `"Consider velocity threshold refinement for merchant cluster"` for decline >= 0.5
- `"Standard review"` as fallback

These are **not specific to the transaction**. A fraud analyst needs:
- Which merchant cluster? What MCC code?
- What velocity window triggered? 1h or 6h?
- What was the card's historical approval rate?
- Are there related transactions to cross-reference?

### Problem 5: Evidence Persistence Requires Feature Flags

**Issue:** `_persist_evidence()` in `pipeline.py` stores evidence envelopes only when insights exist. But the `EvidenceBuilder` creates generic descriptions like `"Pattern velocity detected"`. Counter-evidence and conflict evidence require their respective feature flags to be enabled.

The E2E test expectations all have `should_have_evidence: False` — meaning evidence validation is effectively **opt-out of the test suite**.

### Problem 6: E2E Report Truncates Critical Information

**Issue:** The reporter (`reporter.py`) truncates JSON at 2000 chars and shows `"Large array (N items) - truncated for readability"` for lists > 5 items. For fraud investigations, the *details* matter:
- Card history (which transactions, when, what amounts)
- Pattern scores (which patterns triggered, what details)
- Similarity matches (what prior cases matched)

The report validation stage shows only:
```json
{
  "severity": "LOW",
  "recommendations": 1,
  "evidence": 0,
  "summary": "The transaction shows a single $450 purchase...",
  "recommendation_titles": ["Consider velocity threshold refinement..."]
}
```

This is thin because the `validate_expectations` method deliberately truncates the summary to 200 chars and only shows recommendation titles.

---

## Improvement Plan

### Phase 1: Fix Seed Data for Realistic Patterns (Priority: CRITICAL)

#### 1.1 Enrich Single-Transaction Scenarios with Card History

**Files:** `scripts/seed_test_scenarios.py`

For `seed_likely_fraud`, `seed_approved_likely_fraud`, and similar single-transaction scenarios: **add realistic card history** (5-10 prior transactions on the same card) so the pattern engine has data to score against.

```python
def seed_likely_fraud(conn: psycopg.Connection) -> str:
    """Scenario: Likely fraud — new merchant, elevated amount, first time on card."""
    card_id = f"tok_likely_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-likelyfraud"
    txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(hours=6)

    # ADD: Seed 5 prior normal transactions on this card (creates baseline)
    for i in range(5):
        prior_txn = {
            "id": generate_uuid7(),
            "transaction_id": generate_uuid7(),
            "card_id": card_id,
            "merchant_id": f"test-merchant-likelyfraud-prior-{i}",
            "merchant_category_code": "5411",  # Grocery (normal)
            "amount": 30.0 + (i * 10),  # Normal amounts: $30-$70
            "currency": "USD",
            "timestamp": base_time + timedelta(hours=i),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.05,
            "transaction_context": {
                "ip_country": "US",
                "device_trusted": True,
                "3ds_verified": True,
            },
        }
        insert_transaction(conn, prior_txn)

    # Target transaction: suspicious departure from baseline
    txn = {
        "id": generate_uuid7(),
        "transaction_id": txn_uuid,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "merchant_category_code": "7999",  # Entertainment (departure from grocery)
        "amount": 450.00,  # 6.4x the average ($70 avg)
        "currency": "USD",
        "timestamp": datetime.now(UTC) - timedelta(minutes=5),
        "decision": "DECLINE",
        "decision_reason": "VELOCITY_MATCH",
        "decision_score": 0.65,
        "transaction_context": {
            "ip_country": "US",
            "device_trusted": False,  # New device
            "3ds_verified": False,
        },
        "velocity_snapshot": {
            "velocity_24h": 6,
            "transaction_count_90d": 6,
            "approval_rate_90d": 0.83,
        },
    }
    pk_id = insert_transaction(conn, txn)
    insert_rule_match(conn, pk_id, "NEW_MERCHANT_ELEVATED_AMOUNT", "DECLINE", 0.65)

    return txn_uuid
```

#### 1.2 Add `velocity_snapshot` to All Seed Transactions

The context builder forwards `velocity_snapshot` directly from the transaction row. Currently most seed transactions don't set it, so the LLM prompt shows `velocity_24h: unknown`, `transaction_count_90d: unknown`. Fix by adding realistic velocity snapshots.

#### 1.3 Fix Card Testing Sequence Return ID

Currently `seed_card_testing_sequence` returns `txn_uuid` which is assigned to the history transactions but the pattern engine needs to analyze the *last* transaction. Ensure the returned ID is the final escalation transaction.

---

### Phase 2: Enable Feature Flags for E2E (Priority: HIGH)

#### 2.1 E2E Test Configuration

**Files:** `tests/e2e/test_scenarios.py`, environment configuration

E2E tests should either:
1. Set feature flags via environment variables before running, OR
2. Test against the server's `/health` or config endpoint to detect which features are active, and adjust expectations accordingly

**Recommended approach:** Add a preflight check that queries the server's feature configuration and stores it:

```python
@pytest.fixture(scope="session")
def server_features():
    """Detect server feature flags."""
    response = httpx.get(f"{BASE_URL}/api/v1/ops-agent/health")
    if response.status_code == 200:
        health = response.json()
        return health.get("features", {})
    return {}
```

Then adjust `SCENARIO_EXPECTATIONS` dynamically based on which features are enabled.

#### 2.2 Document Required Environment Variables

Create a checklist of environment variables needed for full-featured E2E testing:

```env
OPS_AGENT_COUNTER_EVIDENCE_ENABLED=true
OPS_AGENT_CONFLICT_MATRIX_ENABLED=true
OPS_AGENT_EXPLANATION_BUILDER_ENABLED=true
OPS_AGENT_ENABLE_LLM_REASONING=true  # default-on; deterministic fallback handles provider issues
OPS_AGENT_NARRATIVE_VERSION=v2
```

---

### Phase 3: Enrich Insight Summaries (Priority: HIGH)

#### 3.1 Improve `_generate_summary` in `recommendation_engine.py`

The current summary is a single sentence. A fraud analyst needs structured context. Enhance the summary to include:

- Transaction details (amount, merchant, MCC, timestamp)
- Card context (age, history depth, approval rate)
- Pattern breakdown with specific scores
- Counter-evidence enumeration
- Data quality flags

```python
def _generate_summary(
    self,
    severity: str,
    pattern_scores: list[Any],
    similarity_result: Any = None,
    context: dict[str, Any] | None = None,
) -> str:
    """Generate detailed deterministic insight summary."""
    details = self._pattern_details(pattern_scores)

    # Transaction context
    transaction = (context or {}).get("transaction")
    amount = getattr(transaction, "amount", 0) if transaction else 0
    merchant_id = getattr(transaction, "merchant_id", "unknown") if transaction else "unknown"

    velocity_snapshot = (context or {}).get("velocity_snapshot") or {}
    tx_count_90d = velocity_snapshot.get("transaction_count_90d", "unknown")
    approval_rate = velocity_snapshot.get("approval_rate_90d", 0)

    parts = []

    # Lead with severity and primary finding
    if severity in ("CRITICAL", "HIGH"):
        parts.append(f"Likely fraud detected ({severity}).")
    elif severity == "MEDIUM":
        parts.append("Moderate fraud risk indicators present.")
    else:
        parts.append("Low fraud risk.")

    # Transaction context line
    parts.append(
        f"Transaction: ${amount:.2f} at merchant {merchant_id}. "
        f"Card history: {tx_count_90d} transactions (90d), "
        f"{approval_rate:.0%} approval rate."
    )

    # Pattern details
    indicators = self._build_indicator_list(details, similarity_result)
    if indicators:
        parts.append(f"Patterns: {'; '.join(indicators)}.")

    # Counter-evidence
    counter = self._counter_evidence_labels(context)
    if counter:
        parts.append(f"Counter-evidence: {', '.join(counter)}.")

    # Missing data flags
    missing = []
    if not velocity_snapshot:
        missing.append("velocity history")
    tx_context = (context or {}).get("transaction_context") or {}
    if "3ds_verified" not in tx_context:
        missing.append("3DS status")
    if "device_trusted" not in tx_context:
        missing.append("device trust")
    if missing:
        parts.append(f"Missing data: {', '.join(missing)}.")

    return " ".join(parts)
```

---

### Phase 4: Enhance Recommendations with Transaction-Specific Details (Priority: MEDIUM)

#### 4.1 Pass Context to Recommendation Candidates

**Files:** `app/agents/recommendation_engine_core.py`

Current recommendations are static strings. Enhance with transaction-specific details:

```python
def generate_recommendations(
    pattern_scores: list[Any],
    similarity_result: Any,
    severity: str,
    context: dict[str, Any],
) -> list[RecommendationCandidate]:
    """Generate context-aware recommendation candidates."""
    candidates = []
    transaction = context.get("transaction")
    tx_context = context.get("transaction_context") or {}
    velocity = context.get("velocity_snapshot") or {}

    amount = getattr(transaction, "amount", 0) if transaction else 0
    merchant_id = getattr(transaction, "merchant_id", "unknown") if transaction else "unknown"
    mcc = getattr(transaction, "merchant_category", "unknown") if transaction else "unknown"

    if severity in ("CRITICAL", "HIGH"):
        candidates.append(
            RecommendationCandidate(
                recommendation_type="review_priority",
                priority=1,
                title="High-priority manual review required",
                impact=f"${amount:.2f} transaction at {merchant_id} (MCC: {mcc}) "
                       f"shows {severity} fraud indicators. Immediate analyst review recommended.",
                signature_hash="review_priority_1",
            )
        )

    velocity_score = _pattern_scores(pattern_scores, "velocity")
    if velocity_score >= 0.6:
        v24h = velocity.get("velocity_24h", "unknown")
        candidates.append(
            RecommendationCandidate(
                recommendation_type="case_action",
                priority=2,
                title="Create velocity investigation case",
                impact=f"Velocity score {velocity_score:.2f} — {v24h} transactions in 24h. "
                       f"Review card activity for burst pattern at {merchant_id}.",
                signature_hash="case_velocity_1",
            )
        )

    # ... similar enrichment for other recommendation types
```

---

### Phase 5: Fix E2E Test Validation & Report (Priority: HIGH)

#### 5.1 Enrich Validation Stage Output

**Files:** `tests/e2e/test_scenarios.py`

The validate_expectations method currently shows a truncated view. Enhance to show a complete fraud analyst dashboard:

```python
def validate_expectations(self, detail: dict[str, Any]) -> bool:
    # ... existing validation logic ...

    if self._reporter:
        # Build comprehensive analyst view
        analyst_view = {
            "severity": severity,
            "summary": summary,  # Full summary, not truncated
            "recommendation_count": len(recommendations),
            "recommendations": [
                {
                    "type": rec.get("recommendation_type", ""),
                    "title": (rec.get("payload") or {}).get("title", ""),
                    "impact": (rec.get("payload") or {}).get("impact", ""),
                    "status": rec.get("status", ""),
                }
                for rec in recommendations
                if isinstance(rec, dict)
            ],
            "evidence_count": len(evidence),
            "evidence_summary": [
                {
                    "kind": e.get("evidence_kind", ""),
                    "category": e.get("category", ""),
                    "strength": e.get("strength", 0),
                    "description": e.get("description", "")[:200],
                }
                for e in evidence[:10]
            ] if evidence else [],
            "model_mode": detail.get("model_mode", "deterministic"),
            "stage_durations": detail.get("stage_durations", {}),
        }

        # Add conflict matrix if present
        if detail.get("conflict_matrix"):
            analyst_view["conflict_matrix"] = detail["conflict_matrix"]

        # Add explanation if present
        if detail.get("explanation"):
            analyst_view["explanation_preview"] = (
                detail["explanation"].get("markdown", "")[:500]
            )

        self._reporter.record_stage(
            stage_name="Fraud Analyst Assessment",
            status=200 if passed else 400,
            elapsed_ms=0,
            request_method="ANALYSIS",
            request_url="validate",
            response_body=analyst_view,
            response_status=200 if passed else 400,
            notes=notes,
        )
```

#### 5.2 Increase Reporter Truncation Limits

**Files:** `tests/e2e/reporter.py`

For fraud investigation reports, the 2000-char truncation is too aggressive:

```python
@staticmethod
def _fmt_json(data: dict | list | None) -> str:
    if data is None:
        return "<em>null</em>"

    # Don't truncate arrays smaller than 20 items
    if isinstance(data, list) and len(data) > 20:
        return f"<em>Large array ({len(data)} items) - truncated for readability</em>"

    json_str = json.dumps(data, indent=2, ensure_ascii=False, default=str)
    # Increase truncation limit for investigation data
    if len(json_str) > 5000:
        json_str = json_str[:5000]
        json_str += "\n... (truncated)"
    # ... rest of highlighting logic
```

#### 5.3 Add Fraud Analyst Dashboard Section to HTML Report

**Files:** `tests/e2e/reporter.py`

Add a new section type in the HTML report that renders a proper fraud analyst card for each scenario:

```html
<div class="analyst-card">
  <div class="severity-badge critical">CRITICAL</div>
  <div class="transaction-info">
    <strong>$1,500.00 USD</strong> at merchant_highamt (MCC: 5947)
    <span class="timestamp">2024-01-15 03:15 UTC</span>
  </div>
  <div class="findings">
    <h4>Key Findings</h4>
    <ul>
      <li><span class="indicator high">●</span> Amount anomaly: $1,500 is 25x average for this card</li>
      <li><span class="indicator medium">●</span> Cross-merchant: 9 unique merchants in 24h</li>
      <li><span class="indicator low">●</span> Counter-evidence: 3DS not verified</li>
    </ul>
  </div>
  <div class="recommendations">
    <h4>Recommended Actions</h4>
    <ol>
      <li>HIGH PRIORITY: Manual review — $1,500 at unfamiliar merchant</li>
      <li>Create velocity investigation case</li>
    </ol>
  </div>
</div>
```

---

### Phase 6: Add Missing Fraud Ops Workflow Stages (Priority: MEDIUM)

#### 6.1 Add Rule Draft Validation to E2E

Currently, the e2e tests don't test the rule draft export flow. Add optional validation when `enable_rule_draft_export` is true.

#### 6.2 Add Multi-Transaction Investigation

Real fraud analysts investigate **clusters** of transactions, not single ones. Add a scenario that:
1. Investigates the initial suspicious transaction
2. Queries card history
3. Investigates related transactions
4. Validates that the system connects related activity

#### 6.3 Add Temporal Consistency Check

The current test seeds use `datetime.now(UTC)` for some scenarios and fixed dates for others (e.g., `datetime(2024, 1, 15, 3, 15, 0)`). The `TIME_UNUSUAL_HOUR` scenario seeds a transaction at `2024-01-15 03:15 UTC` — which is a **fixed date in the past**. The `compute_all_windows` function filters by `datetime.now(UTC) - timedelta(hours=hours)`, so these old transactions **fall outside all windows**.

**Fix:** Use relative timestamps consistently:
```python
# Instead of:
"timestamp": datetime(2024, 1, 15, 3, 15, 0, tzinfo=UTC),
# Use:
today = datetime.now(UTC).replace(hour=3, minute=15, second=0)
"timestamp": today,
```

---

## Implementation Priority

| Phase | Priority | Impact | Effort | Dependencies |
|-------|----------|--------|--------|-------------|
| Phase 1 | CRITICAL | HIGH | Medium | None — seed data fixes are independent |
| Phase 3 | HIGH | HIGH | Low | Phase 1 (richer data → richer summaries) |
| Phase 5 | HIGH | HIGH | Medium | Phase 3 (better summaries → better reports) |
| Phase 2 | HIGH | MEDIUM | Low | None — config changes |
| Phase 4 | MEDIUM | MEDIUM | Low | Phase 1 |
| Phase 6 | MEDIUM | MEDIUM | High | Phases 1-5 |

## Quick Wins (Can Implement Now)

1. **Fix `TIME_UNUSUAL_HOUR` timestamp** — uses `datetime(2024, 1, 15, ...)` which falls outside all windows
2. **Add `velocity_snapshot`** to all seed transactions
3. **Increase reporter truncation** from 2000 to 5000 chars
4. **Remove summary truncation at 200 chars** in validate_expectations
5. **Add counter-evidence to `LIKELY_FRAUD` seed** history to test downgrade path
6. **Set `should_have_evidence: False`** already set, but we should validate *why* it's false and add notes about feature flag state

## How to Validate These Improvements

Run this sequence after implementing changes from the plan:

```bash
# 1) Seed deterministic scenario data
doppler run --config local -- uv run python scripts/seed_test_scenarios.py

# 2) Run scenario e2e suite
uv run pytest tests/e2e/test_scenarios.py -v

# 3) Generate local E2E report (optional consolidated run)
uv run e2e-local
```

Validation checks:
1. Confirm the report includes the `Fraud Analyst Assessment` stage with full summary/recommendation detail.
2. Confirm the report includes the `Similarity Search Analysis` stage with similarity stage latency and top matched transactions.
3. Confirm the report includes the `Agentic Trace Audit` stage with `llm_status`, `llm_model`, `llm_latency_ms`, `llm_reasoning_hash`, and per-stage trace statuses.
4. Confirm analyst output includes `action_plan` and `evidence_gaps` for next-best-action clarity.
3. Confirm seeded scenarios include realistic velocity context (`velocity_snapshot`) in prompts/output.
4. Confirm feature-preflight output is visible in E2E logs and scenario expectations adapt to server flags.
5. Confirm recommendation titles/impacts include transaction-specific context instead of generic text.
6. Confirm report truncation no longer hides key evidence arrays for normal-sized payloads.

## Acceptance KPI Gate (Now Enforced)

The E2E suite now includes `test_acceptance_kpi_gate`, which computes fraud-ops KPIs from all scenario runs and fails the suite if any KPI is below threshold.

| KPI | Threshold | Why it matters for Fraud Ops |
|-----|-----------|------------------------------|
| `scenario_pass_rate` | `1.00` | Every seeded scenario must execute cleanly. |
| `fraud_recall_medium_plus` | `>= 0.80` | High-confidence fraud seeds should mostly surface at `MEDIUM+` severity. |
| `low_risk_precision_low_only` | `1.00` | Legitimate/counter-evidence seeds must stay `LOW`. |
| `recommendation_coverage` | `1.00` | Scenarios that require recommendations must consistently produce them. |
| `run_investigation_p95_ms` | `<= 30000 ms` | Hybrid mode includes external LLM latency and fallback paths; threshold guards practical end-to-end responsiveness. |
| `detail_fetch_p95_ms` | `<= 4000 ms` | Keeps analyst drill-down latency within acceptable bounds. |

Deterministic seed selection is enforced via the generated manifest: `htmlcov/e2e-seed-manifest.json`.

## Playwright CLI Report Review

After a successful run, the custom report is written to `htmlcov/e2e-scenarios-report.html`.

Use Playwright CLI to open and review it:

```bash
npx playwright open htmlcov/e2e-scenarios-report.html
```

Headless verification alternative:

```bash
npx playwright screenshot "file:///C:/Users/kanna/github/card-fraud-ops-analyst-agent/htmlcov/e2e-scenarios-report.html" "htmlcov/e2e-scenarios-report.png"
```

Confirm in the UI:
1. `Acceptance KPI Gate` scenario is present.
2. KPI cards render with pass/fail state.
3. Each scenario shows deterministic `Find Transaction (Seed Manifest)` evidence.

## Expected Outcome

After implementing these changes, the E2E report should show something like:

```json
{
  "severity": "MEDIUM",
  "summary": "Moderate fraud risk indicators present. Transaction: $450.00 at merchant test-merchant-likelyfraud. Card history: 6 transactions (90d), 83% approval rate. Patterns: amount anomaly (6.4x average, elevation from $30-70 baseline to $450); new merchant category (MCC 7999 vs baseline MCC 5411). Missing data: device trust unverified, 3DS not attempted.",
  "recommendation_count": 2,
  "recommendations": [
    {
      "type": "review_priority",
      "title": "Manual review required — elevated amount at new merchant category",
      "impact": "$450.00 at MCC 7999 represents 6.4x the card's average transaction. Card has 83% approval rate over 6 transactions."
    },
    {
      "type": "case_action",
      "title": "Investigate merchant category shift",
      "impact": "Card transitioned from grocery/retail (MCC 5411) to entertainment (MCC 7999) for the first time."
    }
  ],
  "evidence_count": 3,
  "evidence_summary": [
    {"kind": "pattern", "category": "amount_anomaly", "strength": 0.72},
    {"kind": "pattern", "category": "cross_merchant", "strength": 0.45},
    {"kind": "counter_evidence", "category": "none", "strength": 0.0}
  ],
  "model_mode": "deterministic"
}
```

This gives a fraud analyst **actionable context** rather than generic filler text.
