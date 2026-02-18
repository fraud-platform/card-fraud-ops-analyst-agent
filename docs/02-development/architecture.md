# Architecture

## Mission

Build an enterprise-grade Ops Analyst Agent that accelerates fraud investigations while preserving human final authority and auditability.

## Architectural Principles

1. Transaction Management is source of truth.
2. Human analysts are final decision makers.
3. Deterministic evidence before LLM narration.
4. Full traceability for every recommendation and action.
5. Least-privilege data and access boundaries.

## System Context

- Upstream truth: `card-fraud-transaction-management` (`fraud_gov`, TM APIs).
- Peer integration: `card-fraud-rule-management` (draft rule package intake and maker-checker workflow).
- Presentation: `card-fraud-intelligence-portal` embedded analyst workspace.
- Orchestration: `card-fraud-platform` docker and runtime conventions.

## v1 Integration Topology

1. Ops Agent reads from TM DB and TM APIs.
2. Ops Agent generates insights/recommendations.
3. Portal presents recommendations with evidence.
4. Analyst acknowledges or rejects recommendations.
5. Analyst requests draft rule package creation.
6. Draft package is handed off to Rule Management as draft artifact.

## Internal Service Modules

- `context_builder`: deterministic feature extraction from `fraud_gov`.
- `pattern_engine`: deterministic anomaly/pattern scoring.
- `similarity_engine`: deterministic similarity lookups across historical outcomes.
- `reasoning_engine`: bounded LLM narrative generation and recommendation text.
- `recommendation_engine`: policy-constrained recommendation generation.
- `rule_draft_engine`: transforms approved recommendations into rule draft packages.
- `audit_engine`: immutable action and run audit emission.

## Processing Modes

### Continuous mode

- Periodic or near-real-time background scans for high-priority candidate transactions.
- Writes recommendation queue entries for analyst worklists.

### On-demand mode

- Analyst-triggered deep investigation for transaction/case context.
- Returns richer evidence and recommendation detail.

## Data Plane Decision

- v1 does not require direct Kafka consumption.
- Kafka event subscription is reserved for v2 if SLA or latency pressure requires it.

## Reliability Targets (v1)

- P95 quick investigation <= 2 seconds.
- P95 deep investigation <= 8 seconds.
- Recommendation generation failure rate < 1% over 1h windows.

## Cross-Repo Change Surface

- TM: optional query endpoint augmentation for agent needs.
- Rule Management: draft package ingestion API.
- Portal: analyst workspace and recommendation queue UI.
- Platform: service runtime and secrets wiring.

## Async/Await Patterns

This service uses async/await throughout for non-blocking I/O and efficient resource utilization.

### Non-blocking I/O

All database queries, HTTP client calls, and LLM interactions are async:

```python
# All route handlers are async
@router.post("/investigations/run")
async def run_investigation(
    request: RunRequest,
    user: RequireOpsRun,
    session: AsyncSession = Depends(get_session),
):
    service = InvestigationService(session)
    result = await service.run_investigation(...)
    return result
```

### Parallel Query Execution

Use `asyncio.gather()` to execute independent queries concurrently:

```python
# From app/agents/context_builder.py
queries = [
    self.reader.get_transaction_rule_matches(transaction_id),
    self.reader.get_transaction_reviews(transaction_id),
    self.reader.get_analyst_notes(transaction_id),
    self.reader.get_transaction_case(transaction_id),
]

if card_id:
    queries.append(self.reader.get_card_history(card_id, hours_back=72))
if merchant_id:
    queries.append(self.reader.get_merchant_history(merchant_id, hours_back=72))

# Execute all queries in parallel, catching exceptions
results = await asyncio.gather(*queries, return_exceptions=True)

# Unwrap results, checking for exceptions
def unwrap(result: Any, index: int) -> Any:
    if isinstance(result, Exception):
        raise RuntimeError(f"Query {index} failed: {result}") from result
    return result
```

**Key patterns:**
- Pass `return_exceptions=True` to prevent one failure from cancelling all queries
- Explicitly check for exceptions in results to avoid silent failures
- Only add optional queries (card/merchant history) if IDs exist

### Session Management

- Each request gets its own `AsyncSession` via FastAPI dependency injection
- Sessions are automatically closed after request completes
- Never share sessions between requests or concurrent tasks
- Use `session.commit()` explicitly for transactions; auto-commit is disabled

## Input Validation via Pydantic

All request and response data is validated through Pydantic schemas, providing strong type safety and automatic error responses.

### Request Validation

Pydantic schemas validate all input before business logic runs:

```python
# From app/schemas/v1/investigations.py
class RunRequest(BaseModel):
    mode: RunMode = RunMode.QUICK
    transaction_id: str = Field(..., min_length=1, description="Transaction UUID")
    case_id: str | None = None
    include_rule_draft_preview: bool = False

    # SECURITY: Validate UUID format to prevent injection/processing errors
    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, v: str) -> str:
        """Validate transaction_id is a valid UUID format."""
        try:
            UUID(v)
        except ValueError as err:
            raise ValueError("transaction_id must be a valid UUID") from err
        return v
```

**Validation features:**
- Type checking: `str | None` enforces optional strings
- Constraints: `Field(..., min_length=1)` prevents empty strings
- Custom validators: `@field_validator` for complex logic (UUID format)
- Enum enforcement: `RunMode`, `Severity`, etc. restrict values

### UUID Validation

UUIDs are validated at schema boundaries:

```python
@field_validator("transaction_id")
@classmethod
def validate_transaction_id(cls, v: str) -> str:
    try:
        UUID(v)
    except ValueError as err:
        raise ValueError("transaction_id must be a valid UUID") from err
    return v
```

This prevents injection attacks and processing errors from malformed IDs.

### Error Response Format

Validation errors automatically return 400 with details:

```python
# From app/schemas/v1/common.py
class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
```

**Example error response:**
```json
{
  "code": "OPS_AGENT_INVALID_REQUEST",
  "message": "transaction_id must be a valid UUID",
  "details": {
    "field": "transaction_id",
    "value": "not-a-uuid"
  }
}
```

### Response Serialization

All responses are serialized through Pydantic:

```python
@router.get("/{run_id}", response_model=DetailResponse)
async def get_investigation(
    run_id: str,
    user: RequireOpsRead,
    session: AsyncSession = Depends(get_session),
):
    service = InvestigationService(session)
    result = await service.get_investigation(run_id)

    if result is None:
        raise NotFoundError(f"Investigation not found: {run_id}")

    return DetailResponse(**result)  # Validates response structure
```

**Benefits:**
- Type safety: mismatched fields raise errors before HTTP response
- Documentation: OpenAPI schema auto-generated from models
- Consistency: all responses follow same structure
- Filtering: `response_model_exclude_unset` hides default values
