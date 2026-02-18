# Storage and Migrations

## v1 Storage Approach

- Use existing `fraud_gov` schema.
- Add agent-specific tables only.
- Keep TM-owned tables unchanged except for optional indexes supporting read efficiency.

## Migration Strategy

1. Create additive migrations only for v1.
2. Avoid breaking existing TM table contracts.
3. Include rollback scripts for agent-owned objects.
4. Validate permissions immediately after migration.

## Migration Units

- `001_create_ops_agent_tables.sql`
- `002_create_ops_agent_indexes.sql`
- `003_create_ops_agent_constraints.sql`
- `004_create_ops_agent_grants.sql`

## Indexing Guidance

- Index by `transaction_id`, `created_at`, and recommendation `status`.
- Add composite index for queue operations: `(status, created_at DESC)`.
- Add FK indexes for joins from recommendation to insight and draft.

## Integrity Constraints

- Recommendation must reference valid insight.
- Rule draft must reference valid recommendation.
- Audit log entries immutable after insert.

## Compatibility

- Schema changes must be backward-compatible for portal and TM readers.
- New API fields should be additive with documented defaults.

## SQL Injection Prevention

All database queries must use SQLAlchemy's `text()` with bound parameters to prevent SQL injection attacks. Never interpolate values directly into query strings.

### Correct Pattern

```python
from sqlalchemy import text

# Use :param_name placeholders in query
query = text("""
    SELECT id, transaction_id, transaction_amount
    FROM fraud_gov.transactions
    WHERE transaction_id = :transaction_id
      AND decision = :decision
""")

# Pass parameters as dict to execute()
result = await session.execute(query, {
    "transaction_id": txn_id,
    "decision": "DECLINE"
})
```

### Common Anti-Patterns to Avoid

```python
# ❌ WRONG: String interpolation (SQL injection risk)
txn_id = get_user_input()
query = f"SELECT * FROM transactions WHERE id = '{txn_id}'"
result = await session.execute(query)

# ❌ WRONG: % formatting (SQL injection risk)
query = "SELECT * FROM transactions WHERE id = '%s'" % txn_id
result = await session.execute(query)

# ❌ WRONG: .format() (SQL injection risk)
query = "SELECT * FROM transactions WHERE id = '{}'".format(txn_id)
result = await session.execute(query)

# ✅ CORRECT: Parameterized query
query = text("SELECT * FROM transactions WHERE id = :txn_id")
result = await session.execute(query, {"txn_id": txn_id})
```

### JSONB Serialization Best Practices

When working with JSONB columns and asyncpg, always serialize Python dicts to JSON strings using `json.dumps()`:

```python
import json

# ❌ WRONG: Passing raw dict to asyncpg
await session.execute(
    text("INSERT INTO ops_agent_runs (context_snapshot) VALUES (:context)"),
    {"context": {"user_id": "123", "amount": 100}}  # asyncpg error
)

# ✅ CORRECT: Serialize dict to JSON string
await session.execute(
    text("INSERT INTO ops_agent_runs (context_snapshot) VALUES (:context)"),
    {"context": json.dumps({"user_id": "123", "amount": 100})}
)
```

This pattern is required because asyncpg expects JSONB parameters as pre-serialized strings, not raw Python dicts.

### Security Checklist

Every query must satisfy:

- [ ] Uses `text()` for raw SQL (not f-strings or format())
- [ ] All dynamic values use `:parameter` placeholders
- [ ] Parameters passed via dict to `execute()`, not interpolated
- [ ] JSONB values pre-serialized with `json.dumps()`
- [ ] UUID columns converted to strings before asyncpg operations
- [ ] No string concatenation in query construction

### Reference Implementation

See `app/persistence/context_reader.py` for correct parameterized query patterns throughout the codebase. All read-only queries on TM tables follow this security pattern.
