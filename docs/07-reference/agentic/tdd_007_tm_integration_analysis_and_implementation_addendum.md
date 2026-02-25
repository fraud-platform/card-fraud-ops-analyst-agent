# TDD-007: TM Integration Analysis & Implementation Addendum

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document — Addendum
**Related:** TDD-001 through TDD-006, ADR-008, ADR-009

---

## 1. Purpose

This addendum captures findings from a detailed review of `card-fraud-transaction-management` (TM) and identifies:

- Exact TM API → ContextReader mapping (field-by-field)
- Gaps and limitations in TM's current API surface
- Port standardization issues
- Auth/M2M requirements for service-to-service calls
- Recommendations for TM changes (if any)
- Additional implementation notes not covered in TDD-001 through TDD-006

---

## 2. TM API Review Summary

### 2.1 Endpoints Available

| TM Endpoint | Method | Auth | Key For Agent? |
|-------------|--------|------|----------------|
| `GET /api/v1/transactions/{id}` | GET | CurrentUser | **YES** — primary transaction fetch |
| `GET /api/v1/transactions/{id}/overview` | GET | CurrentUser | **YES** — replaces 5 ContextReader methods in 1 call |
| `GET /api/v1/transactions` | GET | CurrentUser | **YES** — card/merchant history with filters |
| `GET /api/v1/transactions/{id}/review` | GET | RequireTxnView | YES — review status |
| `GET /api/v1/transactions/{id}/notes` | GET | RequireTxnView | YES — analyst notes |
| `GET /api/v1/metrics` | GET | CurrentUser | MAYBE — aggregate stats |
| `GET /api/v1/health` | GET | None | YES — health check for circuit breaker |
| `GET /api/v1/cases/{id}` | GET | RequireTxnView | MAYBE — case details |
| `GET /api/v1/worklist` | GET | RequireTxnView | NO — not agent's concern |
| `POST /api/v1/cases` | POST | RequireTxnView | FUTURE — agent-created cases |
| `POST /api/v1/transactions/{id}/notes` | POST | RequireTxnView | FUTURE — agent-authored notes |

### 2.2 Golden Endpoint: `/overview`

**`GET /api/v1/transactions/{transaction_id}/overview?include_rules=true`** returns:

```python
{
    "transaction": TransactionQueryResult,  # Full transaction with all fields
    "review": dict | None,                 # Review status, priority, analyst, resolution
    "notes": list[dict],                   # All analyst notes
    "case": dict | None,                   # Linked case (if any)
    "matched_rules": list[dict],           # Rule match details
    "last_activity_at": datetime | None
}
```

This **single call replaces 5 of our 7 ContextReader methods**:
- `get_transaction()` ✅
- `get_transaction_rule_matches()` ✅
- `get_transaction_reviews()` ✅
- `get_analyst_notes()` ✅
- `get_transaction_case()` ✅

Remaining calls needed separately:
- `get_card_history()` → `GET /transactions?card_id=X&from_date=Y&page_size=500`
- `get_merchant_history()` → `GET /transactions?merchant_id=X&from_date=Y&page_size=500`

---

## 3. Context Reader → TM Client: Field Name Translation

The current `context_reader.py` uses SQL aliases to rename TM DB columns to match our core logic's expectations. The new TM client must perform the same translation since TM's API returns the original field names.

### 3.1 Transaction Fields

| TM API Field Name | Our Core Logic Expects | Current SQL Alias |
|-------------------|----------------------|-------------------|
| `transaction_amount` | `amount` | `transaction_amount AS amount` |
| `transaction_currency` | `currency` | `transaction_currency AS currency` |
| `merchant_category_code` | `merchant_category` | `merchant_category_code AS merchant_category` |
| `card_last4` | `card_last_four` | `card_last4 AS card_last_four` |
| `decision` | `status` | `decision AS status` |
| `decision_reason` | `decline_reason` | `decision_reason AS decline_reason` |
| `decision_score` | `fraud_score` | `decision_score AS fraud_score` |
| `velocity_snapshot` | `velocity_snapshot` | (no alias needed) |
| `velocity_results` | `velocity_results` | (no alias needed) |
| `transaction_context` | `transaction_context` | (no alias needed) |
| `transaction_id` | `transaction_id` | (no alias needed) |
| `card_id` | `card_id` | (no alias needed) |
| `merchant_id` | `merchant_id` | (no alias needed) |
| `risk_level` | `risk_level` | (no alias needed) |
| `transaction_timestamp` | `transaction_timestamp` | (no alias needed) |

### 3.2 Rule Match Fields

| TM API Field Name | Our Core Logic Expects | Current SQL Alias |
|-------------------|----------------------|-------------------|
| `rule_id` | `rule_id` | (no alias) |
| `rule_name` | `rule_name` | (no alias) |
| `evaluated_at` | `triggered_at` | `evaluated_at AS triggered_at` |
| `rule_action` | `action` | `rule_action AS action` |
| `match_score` | `score` | `match_score AS score` |
| `rule_output` | `metadata` | `rule_output AS metadata` |
| `matched` | `matched` | (no alias) |
| `contributing` | `contributing` | (no alias) |
| `match_reason` | `match_reason` | (no alias) |

### 3.3 Review Fields

| TM API Field Name | Our Core Logic Expects | Current SQL Alias |
|-------------------|----------------------|-------------------|
| `assigned_analyst_id` | `reviewed_by` | `assigned_analyst_id AS reviewed_by` |
| `first_reviewed_at` | `reviewed_at` | `first_reviewed_at AS reviewed_at` |
| `resolution_code` | `decision` | `resolution_code AS decision` |
| `resolution_notes` | `notes` | `resolution_notes AS notes` |
| `status` | `status` | (no alias) |
| `priority` | `priority` | (no alias) |
| `case_id` | `case_id` | (no alias) |

### 3.4 Notes Fields

| TM API Field Name | Our Core Logic Expects | Current SQL Alias |
|-------------------|----------------------|-------------------|
| `note_content` | `note_text` | `note_content AS note_text` |
| `analyst_id` | `created_by` | `analyst_id AS created_by` |
| `analyst_name` | `analyst_name` | (no alias) |
| `note_type` | `note_type` | (no alias) |
| `created_at` | `created_at` | (no alias) |

### 3.5 Case Fields

| TM API Field Name | Our Core Logic Expects | Current SQL Alias |
|-------------------|----------------------|-------------------|
| `case_number` | `case_id` | `case_number AS case_id` |
| `case_type` | `case_type` | (no alias) |
| `case_status` | `status` | `case_status AS status` |
| `assigned_analyst_id` | `assigned_to` | `assigned_analyst_id AS assigned_to` |
| `risk_level` | `priority` | `risk_level AS priority` |
| `title` | `title` | (no alias) |
| `created_at` | `created_at` | (no alias) |

### 3.6 Implementation: Field Mapping in TMClient

```python
# app/clients/tm_client.py — field mapping layer

TRANSACTION_FIELD_MAP = {
    "transaction_amount": "amount",
    "transaction_currency": "currency",
    "merchant_category_code": "merchant_category",
    "card_last4": "card_last_four",
    "decision": "status",
    "decision_reason": "decline_reason",
    "decision_score": "fraud_score",
}

RULE_MATCH_FIELD_MAP = {
    "evaluated_at": "triggered_at",
    "rule_action": "action",
    "match_score": "score",
    "rule_output": "metadata",
}

REVIEW_FIELD_MAP = {
    "assigned_analyst_id": "reviewed_by",
    "first_reviewed_at": "reviewed_at",
    "resolution_code": "decision",
    "resolution_notes": "notes",
}

NOTE_FIELD_MAP = {
    "note_content": "note_text",
    "analyst_id": "created_by",
}

CASE_FIELD_MAP = {
    "case_number": "case_id",
    "case_status": "status",
    "assigned_analyst_id": "assigned_to",
    "risk_level": "priority",
}


def _remap(data: dict, field_map: dict) -> dict:
    """Remap TM API field names to our core logic field names."""
    result = {}
    for key, value in data.items():
        mapped_key = field_map.get(key, key)
        result[mapped_key] = value
    return result
```

---

## 4. TM API Gaps & Limitations

### 4.1 Critical: No `user_id`/`account_id` Filter

TM does NOT have a `user_id` or `account_id` column on the `transactions` table. The finest entity granularity is `card_id`.

**Impact**: ADR-008 mentions "user risk profile" as a tool. This is **not possible** with current TM schema.

**Workaround**: Use `card_id` as the entity proxy. In fraud ops, card-level analysis is the standard. A "user profile" would be approximated by analyzing all transactions for a card. If multi-card per user is needed, this requires a TM schema change (out of scope).

**Decision**: Proceed with card-level only. Document as known limitation.

### 4.2 No Dedicated Merchant Profile Endpoint

TM has no `/merchants/{id}` endpoint. Merchant data is only available as embedded fields on transactions (`merchant_id`, `merchant_category_code`, MCC).

**Impact**: Our `context_builder_core.py` takes a `merchant_name` field, but TM doesn't store merchant names.

**Workaround**:
- `merchant_name` will be empty string (already has `""` default in `TransactionContext`)
- Merchant "profile" is computed from transaction history: `GET /transactions?merchant_id=X&from_date=Y`
- We compute merchant stats (transaction counts, avg amount, unique cards) in `compute_window_stats()`

**Decision**: No TM change needed. Compute merchant profile from transaction history.

### 4.3 No Live Velocity/Aggregate Computation

TM stores velocity data as **frozen JSONB snapshots** at decision time (`velocity_snapshot`, `velocity_results`). It does NOT compute live velocity windows.

**Impact**: Our `compute_all_windows()` function in `context_builder_core.py` computes 1h/6h/24h/72h windows from raw transaction lists. This remains valid.

**Workaround**:
1. Fetch card/merchant history via `GET /transactions?card_id=X&from_date=Y`
2. Pass raw transaction lists to `compute_all_windows()` (existing pure logic)
3. Also extract `velocity_snapshot` from the target transaction for supplementary data

**Decision**: No TM change needed. Continue computing windows client-side.

### 4.4 Pagination Limit: Max 500 Transactions Per Page

TM list endpoint caps `page_size` at 500. For high-velocity cards with > 500 transactions in a 72h window, we'd miss data.

**Impact**: Unlikely in practice (500 txns in 72h is extreme), but theoretically possible.

**Workaround**:
1. Set `page_size=500` (maximum)
2. If `has_more=true`, follow `next_cursor` for additional pages
3. Set a hard limit of 3 pages (1500 transactions) to prevent runaway cost
4. For most scenarios, 500 is more than sufficient

**Implementation Note**: TMClient must support cursor-follow pagination:

```python
async def get_card_history(self, card_id: str, hours_back: int = 72) -> list[dict]:
    """Fetch card history with auto-pagination (max 3 pages)."""
    from_date = (datetime.now(UTC) - timedelta(hours=hours_back)).isoformat()
    all_items = []
    cursor = None

    for _ in range(3):  # Max 3 pages = 1500 txns
        params = {"card_id": card_id, "from_date": from_date, "page_size": 500}
        if cursor:
            params["cursor"] = cursor

        response = await self._get("/api/v1/transactions", params=params)
        data = response.json()
        all_items.extend(data["items"])

        if not data.get("has_more"):
            break
        cursor = data.get("next_cursor")

    return [_remap(item, TRANSACTION_FIELD_MAP) for item in all_items]
```

### 4.5 No Embedding/Vector Endpoints in TM

TM has zero vector/embedding capability. Our ops-agent handles this independently (pgvector on `ops_agent_transaction_embeddings` table).

**Decision**: No TM change needed. This is correctly our responsibility as defined in TDD-003.

### 4.6 `country` Filter is Fake

TM accepts `country` as a query parameter on `GET /transactions` but it is **not persisted and not applied**. It exists only for API compatibility.

**Impact**: If we want to filter by geolocation, we'd need `transaction_context` JSONB post-filtering.

**Decision**: Don't rely on country filter. Location data is available inside `transaction_context` JSONB if present. Process it client-side.

---

## 5. Port Standardization

**Discrepancy found:**

| Source | TM Port |
|--------|---------|
| TM repo `config.py` default | `8080` |
| Ops-agent E2E tests | `8002` |
| TDD-003 (our design doc) | `8001` |

**Root cause**: The platform `docker-compose.yml` maps TM to port 8002 externally. The TM container itself listens on 8080 internally.

**Resolution**:
- Use environment variable `TM_BASE_URL` everywhere (already the pattern)
- Default should be `http://localhost:8002` (matching platform compose and existing E2E tests)
- Update TDD-003's config default from `8001` to `8002`

---

## 6. Auth: M2M Token for Service-to-Service Calls

### 6.1 Current Auth Model

| Service | Auth Dependency | Required Scopes |
|---------|----------------|-----------------|
| TM endpoints (transactions, query) | `CurrentUser` | Any authenticated user |
| TM endpoints (reviews, notes, cases) | `RequireTxnView` | `txn:view` permission |
| Ops-agent endpoints | `require_scope()` | `ops_agent:read`, `ops_agent:run`, etc. |

### 6.2 Agent → TM Calls: Auth Strategy

When ops-agent calls TM as a backend service, we need a service-to-service (M2M) token.

**Options:**

| Option | Pros | Cons |
|--------|------|------|
| A. **Forward user JWT** | Simple, preserves user context, natural RBAC | Doesn't work for background/scheduled runs |
| B. **M2M client credentials** | Works without user, standard OAuth2 | No user context in TM audit logs |
| C. **Hybrid** (forward when available, M2M fallback) | Best of both | More complex implementation |

**Recommendation: Option C (Hybrid)**

```python
class TMClient:
    async def _get_auth_header(self, user_token: str | None = None) -> dict[str, str]:
        """Get auth header for TM API calls."""
        if user_token:
            # Forward user's JWT for user-initiated investigations
            return {"Authorization": f"Bearer {user_token}"}
        else:
            # Use M2M token for background/scheduled investigations
            token = await self._get_m2m_token()
            return {"Authorization": f"Bearer {token}"}
```

### 6.3 Required Doppler Secrets (Additional)

| Secret | Description | Example |
|--------|-------------|---------|
| `TM_BASE_URL` | Transaction Management API base URL | `http://localhost:8002` |
| `TM_M2M_CLIENT_ID` | M2M client ID for TM API access | (from Auth0) |
| `TM_M2M_CLIENT_SECRET` | M2M client secret for TM API access | (from Auth0) |
| `TM_M2M_AUDIENCE` | TM API audience in Auth0 | `https://fraud-transaction-management-api` |

### 6.4 Local Development Bypass

In local dev (`SECURITY_SKIP_JWT_VALIDATION=true`), both services skip JWT validation. The TMClient should still send a token header (even a dummy one) for consistency:

```python
if self.config.skip_jwt_validation:
    return {"Authorization": "Bearer dev-skip-validation"}
```

---

## 7. TM API Call Optimization

### 7.1 Optimal Call Pattern for Context Building

```
┌─────────────────────────────────────────────┐
│  Step 1: GET /transactions/{id}/overview    │  ← Single call replaces 5 queries
│  Returns: transaction, review, notes,       │
│           case, matched_rules               │
├─────────────────────────────────────────────┤
│  Step 2 (parallel):                         │
│  ├── GET /transactions?card_id=X&from=Y     │  ← Card history
│  └── GET /transactions?merchant_id=X&from=Y │  ← Merchant history
└─────────────────────────────────────────────┘

Total: 3 HTTP calls (was 7 SQL queries)
```

### 7.2 TMClient Method Signatures (Refined from TDD-003)

```python
class TMClient:
    """Async HTTP client for Transaction Management API."""

    async def get_transaction_overview(
        self, transaction_id: str, include_rules: bool = True
    ) -> dict[str, Any]:
        """Fetch full transaction overview (transaction + review + notes + case + rules).

        Replaces: get_transaction, get_rule_matches, get_reviews, get_notes, get_case
        """

    async def get_card_history(
        self, card_id: str, hours_back: int = 72, max_pages: int = 3
    ) -> list[dict[str, Any]]:
        """Fetch card transaction history with auto-pagination."""

    async def get_merchant_history(
        self, merchant_id: str, hours_back: int = 72, max_pages: int = 3
    ) -> list[dict[str, Any]]:
        """Fetch merchant transaction history with auto-pagination."""

    async def health_check(self) -> bool:
        """Check TM API availability (for circuit breaker)."""
```

### 7.3 Error Handling & Resilience

The TMClient must handle:

| Scenario | Response | Agent Behavior |
|----------|----------|----------------|
| TM returns 404 | Transaction not found | Raise `NotFoundError` — investigation cannot proceed |
| TM returns 401/403 | Auth failure | Raise `DependencyError` — retry with fresh M2M token once |
| TM returns 500 | Server error | Retry with exponential backoff (max 3 retries via tenacity) |
| TM timeout | No response | Raise `DependencyError` after timeout (10s default) |
| TM down | Connection refused | Circuit breaker opens after 3 consecutive failures |

```python
from tenacity import retry, stop_after_attempt, wait_exponential

class TMClient:
    @retry(stop=stop_after_attempt(3), wait=wait_exponential(multiplier=1, max=10))
    async def _get(self, path: str, params: dict | None = None) -> httpx.Response:
        """HTTP GET with retry and circuit breaker."""
        response = await self._client.get(path, params=params, headers=await self._auth_headers())
        response.raise_for_status()
        return response
```

---

## 8. Changes Required in TM Repo

After thorough review: **No code changes required in TM.**

TM already provides everything we need:

| Agent Need | TM Provides | Status |
|------------|-------------|--------|
| Transaction details | `GET /transactions/{id}` | ✅ Available |
| Full context (txn + review + notes + case + rules) | `GET /transactions/{id}/overview` | ✅ Available |
| Card history with time filter | `GET /transactions?card_id=X&from_date=Y` | ✅ Available |
| Merchant history with time filter | `GET /transactions?merchant_id=X&from_date=Y` | ✅ Available |
| Amount range filter | `GET /transactions?min_amount=X&max_amount=Y` | ✅ Available |
| Risk level filter | `GET /transactions?risk_level=HIGH` | ✅ Available |
| Keyset pagination | `cursor` / `next_cursor` / `has_more` | ✅ Available |
| Health check | `GET /health` | ✅ Available |
| Review status | `GET /transactions/{id}/review` | ✅ Available |
| Analyst notes | `GET /transactions/{id}/notes` | ✅ Available |
| Case details | `GET /cases/{id}` | ✅ Available |
| Velocity data | `velocity_snapshot` / `velocity_results` on transaction | ✅ Available |

### 8.1 Nice-to-Have (Future, Non-Blocking)

These would improve the agent but are NOT required for Phase 1:

| Enhancement | Benefit | Priority |
|-------------|---------|----------|
| `POST /transactions/batch` (batch fetch by IDs) | Reduce HTTP calls for similarity matching | P3 |
| `user_id` / `account_id` column + filter | Enable user-level profiling | P3 (schema change) |
| `GET /merchants/{id}/profile` endpoint | Dedicated merchant risk profile | P3 |
| Dedicated velocity window endpoint | Live velocity computation | P4 (we compute client-side) |

---

## 9. Additional Implementation Considerations

### 9.1 `context_builder_core.py` — No Changes Needed

Good news: `assemble_context()` accepts raw dicts, not ORM models. It doesn't care whether data came from SQL or HTTP. The field name translation happens in the TMClient layer (section 3.6 above), so **`context_builder_core.py` continues to work unchanged**.

The data flow becomes:

```
Before: ContextReader(SQL) → raw dicts → assemble_context() → context dict
After:  TMClient(HTTP) → raw dicts (remapped) → assemble_context() → context dict
```

### 9.2 `velocity_snapshot` Deep Structure

TM stores velocity data as JSONB. The internal structure depends on the Rule Engine configuration:

```python
# Example velocity_snapshot from TM
{
    "card_velocity": {
        "1h": {"count": 3, "total": 450.00},
        "24h": {"count": 12, "total": 3200.00}
    },
    "merchant_velocity": {
        "1h": {"count": 1, "total": 150.00}
    }
}
```

Our core logic currently extracts `velocity_score` from the transaction dict (which was aliased from `decision_score`). The frozen snapshot provides supplementary data. We should expose it to the Planner/Reasoning tool for richer LLM context.

### 9.3 `transaction_context` JSONB — Unexplored Gold Mine

The `transaction_context` field contains the **full evaluation context** from the Rule Engine at decision time. This may include:
- Device fingerprint info
- IP/geo data
- Channel metadata
- Authentication method
- Session risk signals

This is currently passed through to `assemble_context()` but not deeply analyzed. The reasoning tool should include it in LLM context for richer analysis.

### 9.4 `matched_rules` From `/overview` vs. Separate Fetch

When using `/overview?include_rules=true`, rule matches are embedded in the response as `matched_rules: list[dict]`. However, the field names in the API response may differ slightly from the raw DB column names (TM's schema layer may already alias them).

**Action**: During implementation, verify the exact field names in `matched_rules` from the `/overview` response against what our `RULE_MATCH_FIELD_MAP` expects. If TM's Pydantic schema already renames them, we may need less remapping.

### 9.5 Dual ID System in TM

TM has **two UUID columns** on transactions:
- `id` — Internal row PK (UUIDv7, generated by TM)
- `transaction_id` — Business key from Rule Engine

**Critical**: Our agent always uses `transaction_id` (business key) for lookups. TM's API correctly routes by business key. But some TM response fields (like `review.transaction_id`) reference the PK `id`, not the business `transaction_id`.

**Action**: The TMClient must be aware of this and always use the business `transaction_id` for external interactions. Never expose TM's internal `id` to agent logic.

### 9.6 Overview Endpoint `include_rules` Default

The `/overview` endpoint defaults `include_rules=False`. Our TMClient must always pass `include_rules=True` since rule matches are essential for pattern analysis.

### 9.7 Time Zone Handling

TM stores all timestamps as `TIMESTAMPTZ` and returns them in ISO 8601 with timezone. Our `context_builder_core.py` has `_coerce_datetime()` that handles both naive and aware datetimes, plus ISO string parsing. This will continue to work with HTTP response strings.

### 9.8 LangGraph Checkpointing vs. TM API Idempotency

LangGraph supports state checkpointing for fault tolerance. If the graph resumes after a crash:
- `context_tool` would re-call TM APIs → idempotent GETs, safe
- `recommendation_tool` would re-persist to our DB → idempotent via `ON CONFLICT DO UPDATE`, safe

But the TM API calls have cost (network latency). To avoid redundant calls on resume:
- Check `state["context"]` before calling TM
- If context is already populated, skip the TM call

```python
class ContextTool(BaseTool):
    async def execute(self, state: InvestigationState) -> dict:
        if state.get("context"):
            # Already populated (resume case), skip TM calls
            return state
        # ... proceed with TM API calls
```

### 9.9 Structured Logging for TM Calls

All TM API calls should log with structured fields for observability:

```python
structlog.get_logger().info(
    "tm_api_call",
    method="GET",
    path="/api/v1/transactions/{id}/overview",
    transaction_id=txn_id,
    latency_ms=elapsed,
    status_code=response.status_code,
    investigation_id=state["investigation_id"],
)
```

### 9.10 OTel Trace Propagation to TM

The TMClient should propagate OpenTelemetry trace context to TM so distributed traces span both services:

```python
from opentelemetry.propagate import inject

async def _get(self, path: str, ...) -> httpx.Response:
    headers = await self._auth_headers()
    inject(headers)  # Adds traceparent header
    return await self._client.get(path, headers=headers, ...)
```

---

## 10. Dependency Version Pinning

### 10.1 New Dependencies to Add

```toml
# pyproject.toml additions
dependencies = [
    # ... existing ...
    "langgraph>=0.3.0",
    "langchain-core>=0.3.0",
    "langchain-ollama>=0.3.0",
    "langchain-anthropic>=0.3.0",  # Optional: for Claude model support
]
```

### 10.2 Dependencies to Remove

```toml
# Remove from pyproject.toml
# "litellm>=1.78.0"  — replaced by langchain-*
```

### 10.3 Dependencies to Keep

```toml
# Keep as-is
"httpx>=0.28.0"              # Used by TMClient (already a dependency)
"tenacity>=9.0.0"            # Used for retry logic on TM calls (already present)
"opentelemetry-api>=1.30.0"  # OTel trace propagation
"structlog>=25.1.0"          # Structured logging
"pydantic>=2.10.0"           # Schema validation
```

---

## 11. Implementation Sequencing Refinement

Based on the TM review, the implementation order from TDD-001 should be refined:

### Phase 0: Preparation (Before Any Code Changes)

1. **Verify TM is running locally**: `curl http://localhost:8002/api/v1/health`
2. **Verify TM has test data**: `curl http://localhost:8002/api/v1/transactions?page_size=1`
3. **Check TM `/overview` endpoint shape**: Manually call it once and save the response for test fixtures
4. **Add `TM_BASE_URL` to Doppler**: All configs (local, local-test, test, prod)
5. **Capture TM OpenAPI spec**: `curl http://localhost:8002/openapi.json > docs/tm-openapi-snapshot.json`

### Phase 1: TMClient First (Foundation)

Build and test the TMClient **before** any agent/tool work, because:
- Every tool depends on TMClient data
- Field mapping must be verified against real TM responses
- Circuit breaker behavior must be proven

### Updated Implementation Order

| Step | Component | Depends On | Validates |
|------|-----------|-----------|-----------|
| 1 | `InvestigationState` TypedDict | Nothing | State schema |
| 2 | `TMClient` + field mapping | Step 1 | TM API integration |
| 3 | `ToolRegistry` + `BaseTool` | Step 1 | Tool framework |
| 4 | `context_tool` | Steps 2, 3 | TM → state population |
| 5 | Move `*_core.py` to `app/tools/_core/` | Nothing | Import paths |
| 6 | `pattern_tool`, `similarity_tool` | Steps 3, 5 | Analysis tools |
| 7 | LangChain ChatModel factory | Nothing | LLM provider |
| 8 | `reasoning_tool` | Steps 3, 7 | LLM integration |
| 9 | `recommendation_tool`, `rule_draft_tool` | Steps 3, 5 | Output tools |
| 10 | `Planner` node | Steps 3, 7 | Tool selection |
| 11 | `ToolExecutor` + `Completion` nodes | Steps 3, 10 | Graph nodes |
| 12 | `build_investigation_graph()` | Steps 10, 11 | Full graph |
| 13 | `StateStore` + persistence | Step 12 | State persistence |
| 14 | `InvestigationService` | Steps 12, 13 | Service layer |
| 15 | API routes | Step 14 | HTTP endpoints |
| 16 | Quality gates | All | Full validation |

---

## 12. Risk Register

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| TM API response shape changes without notice | Medium | High | Pin snapshot of `/overview` response in test fixtures; version TM API calls |
| TM field names differ from what SQL aliases produced | High | Medium | Verify mapping against real TM `/overview` response in Phase 0 |
| Card history > 500 txns in window | Low | Low | Auto-pagination with 3-page cap |
| M2M token acquisition latency | Low | Medium | Cache M2M token (they last 24h typically) |
| TM downtime during investigation | Medium | High | Circuit breaker + DependencyError → graph pauses, resumes later |
| LangGraph version breaking changes | Medium | Medium | Pin `langgraph>=0.3.0,<0.4.0` initially |
| Ollama model unavailable locally | Low | High | Deterministic planner fallback (already designed in TDD-002) |

---

## 13. Pre-Implementation Verification Checklist

Before writing any implementation code, verify:

- [ ] TM service running at `http://localhost:8002` and healthy
- [ ] `GET /api/v1/transactions?page_size=1` returns at least 1 transaction
- [ ] `GET /api/v1/transactions/{id}/overview?include_rules=true` returns full shape
- [ ] Save example `/overview` response as `tests/fixtures/tm_overview_response.json`
- [ ] Save example `/transactions` list response as `tests/fixtures/tm_list_response.json`
- [ ] `TM_BASE_URL=http://localhost:8002` added to Doppler (local, local-test)
- [ ] TM OpenAPI spec captured for reference
- [ ] Existing quality gates pass: `uv run ruff check app/ tests/ && uv run ruff format --check app/ tests/ && uv run pytest tests/unit tests/smoke -v`
- [ ] Git branch created for transformation work
- [ ] All 9 ADRs and 7 TDDs committed to repo
