# Velocity Architecture — Quick Reference

## TL;DR

**The current architecture works correctly.** No changes needed. PatternEngine sees all historical transactions and computes accurate velocity scores.

---

## The Core Question

> "When we investigate the last transaction in a velocity_burst scenario (12 tx in 1h), does PatternEngine see the first 11 transactions?"

**Answer**: **YES.**

---

## Why It Works

### 1. Seed Creates Full History

```python
# seed_test_scenarios.py
for i in range(12):
    txn = {
        "card_id": "tok_burst_abc123",  # ← SAME card for all 12
        "timestamp": base_time + timedelta(minutes=i * 5),  # ← 0, 5, 10, ..., 55 min
        ...
    }
    insert_transaction(conn, txn)  # ← All 12 committed
```

### 2. Card History Query Is Inclusive

```sql
SELECT transaction_id, amount, transaction_timestamp, ...
FROM fraud_gov.transactions
WHERE card_id = 'tok_burst_abc123'
  AND transaction_timestamp >= NOW() - INTERVAL '24 hours'
-- No "AND transaction_id != :current_id" clause
```

**Returns**: ALL 12 transactions (including the current one)

### 3. Pattern Engine Counts Transactions

```python
# context_builder_core.py
def compute_window_stats(transactions):
    return WindowStats(
        transaction_count=len(transactions),  # ← 12
        ...
    )

# pattern_engine_core.py
if window_stats[1].transaction_count > 10:  # ← 12 > 10 = TRUE
    score = 0.9  # ← TRIGGERS
```

---

## Data Flow Diagram

```
Seed Script (12 tx)
    ↓
fraud_gov.transactions (12 rows)
    ↓
Test investigates txn #12
    ↓
get_card_history(card_id) → Returns ALL 12 rows
    ↓
compute_all_windows() → window_stats[1].transaction_count = 12
    ↓
score_velocity_patterns() → 12 > 10 → score = 0.9
    ↓
Test validates pattern_score >= 0.9 → PASS
```

---

## Should We Cache Velocity?

**NO.** Follow analytics-agent pattern:

| Approach | Pros | Cons | Verdict |
|----------|------|------|---------|
| **Compute on-the-fly** (current) | • Always accurate<br>• Single source of truth<br>• Simple | • Slower (mitigated by indexes) | ✅ **RECOMMENDED** |
| **Store in ops_agent tables** | • Fast queries<br>• Trend analysis | • Staleness risk<br>• Duplication<br>• Complex invalidation | ❌ **NOT RECOMMENDED** |

---

## Performance Optimization

If queries are slow (unlikely):

1. **Add composite index**:
   ```sql
   CREATE INDEX idx_transactions_card_timestamp
   ON fraud_gov.transactions(card_id, transaction_timestamp DESC);
   ```

2. **Benchmark**: Target <100ms for 24h window query

3. **Only cache if** >500ms (use Redis with TTL=300)

---

## Scenario Validation

All velocity scenarios pass with current architecture:

| Scenario | Seed Data | Expected Score | Actual Score | Status |
|----------|-----------|----------------|--------------|--------|
| velocity_burst | 12 tx in 1h | 0.9 (12 > 10) | 0.9 | ✅ PASS |
| cross_merchant_spread | 11 merchants in 24h | 0.8 (11 > 10) | 0.8 | ✅ PASS |
| high_decline_ratio | 6/10 declines = 60% | 0.9 (0.6 > 0.5) | 0.9 | ✅ PASS |
| card_testing_pattern | 5 declines | 0.9 (ratio=1.0) | 0.9 | ✅ PASS |

---

## Key Files

| File | Purpose |
|------|---------|
| `scripts/seed_test_scenarios.py` | Creates full transaction history |
| `app/persistence/context_reader.py` | Queries card history (includes all txns) |
| `app/agents/context_builder_core.py` | Computes window stats from raw data |
| `app/agents/pattern_engine_core.py` | Scores velocity patterns |
| `tests/e2e/test_scenarios.py` | Validates pattern scores |

---

## Common Misconceptions

### ❌ "The current transaction is excluded from history"

**Fact**: The query does NOT filter out the current transaction. Returns ALL rows matching card_id + time window.

### ❌ "Seed data only creates the current transaction"

**Fact**: Seed scenarios create ALL transactions in the pattern (12 rows for velocity_burst).

### ❌ "Pattern engine uses TM's velocity_snapshot"

**Fact**: Pattern engine computes velocity from raw transaction count, not TM's pre-computed values.

---

## Recommended Actions

### Immediate ✅ Already Done

- Seed scripts create full history
- Card history queries are inclusive
- Pattern engine computes correctly
- Tests validate scores

### Short-term (Optional)

- Add composite index for performance
- Benchmark query latency
- Document architecture decisions

### Long-term (If Needed)

- Materialized views for analytics dashboards (NOT for investigation pipeline)
- Redis caching only if queries >500ms

---

## Summary

✅ **Current architecture is correct**
✅ **No changes needed**
✅ **Follows analytics-agent best practices**
✅ **Tests validate expected behavior**

**DO NOT** store separate velocity aggregations in ops_agent tables.
