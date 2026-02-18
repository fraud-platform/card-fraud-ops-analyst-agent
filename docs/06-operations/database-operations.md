# Database Operations

## Overview

This document provides operational guidance for database-specific tasks in the Card Fraud Ops Analyst Agent. It covers connection pool management, query optimization patterns, index maintenance, monitoring, and troubleshooting common database issues.

The service uses PostgreSQL with asyncpg driver, connecting to the shared `fraud_gov` schema. All ops_agent tables are prefixed with `ops_agent_` to maintain clear ownership boundaries.

## Connection Pool Tuning

### Pool Configuration

The connection pool is configured in `app/core/database.py` with environment variables:

```python
DATABASE_POOL_SIZE=10          # Base pool size per worker
DATABASE_MAX_OVERFLOW=10       # Additional connections under load
DATABASE_POOL_TIMEOUT=30       # Seconds to wait for available connection
DATABASE_POOL_RECYCLE=1800     # Recycle connections after 30 minutes
```

Important:
- Do not encode pool settings in `DATABASE_URL_*` query strings (for example `?pool_size=20`).
- `asyncpg` treats unknown DSN query keys as connect kwargs and raises runtime `TypeError`.
- Set pool values only via `DATABASE_POOL_SIZE`, `DATABASE_MAX_OVERFLOW`, `DATABASE_POOL_TIMEOUT`, `DATABASE_POOL_RECYCLE`.

### Sizing Guidelines

**Total connections calculation:**
```
total_connections = (pool_size + max_overflow) × workers
```

**Default configuration (4 workers):**
- Pool size per worker: 10
- Max overflow per worker: 10
- Total per worker: 20
- **Total across 4 workers: 80**

**PostgreSQL server limits:**
- Ensure PostgreSQL `max_connections` setting allows for:
  - 80 connections for ops-agent
  - Connections from sibling services (rule-management, transaction-management)
  - Connections from monitoring tools
- Typical production `max_connections`: 200-300

### Tuning Parameters

#### `pool_size`

Base number of persistent connections per worker process.

- **Too low**: Connection wait time increases under load
- **Too high**: Wasted resources, PostgreSQL connection limits
- **Starting point**: 10-20 per worker
- **Adjust based on**: Avg concurrent queries per worker

#### `max_overflow`

Additional connections created when pool is exhausted.

- **Default**: 10
- **Purpose**: Handle traffic spikes
- **Monitor**: If frequently hitting overflow, increase base `pool_size`
- **Check**: `pool_overflow` metric in observability dashboards

#### `pool_timeout`

Seconds to wait for available connection before raising error.

- **Default**: 30 seconds
- **Too short**: False failures during load spikes
- **Too long**: Poor user experience during pool exhaustion
- **Recommendation**: 30 seconds (matches statement timeout)

#### `pool_recycle`

Seconds after which a connection is closed and replaced.

- **Default**: 1800 (30 minutes)
- **Purpose**: Prevent stale connections, avoid PostgreSQL-side timeouts
- **Adjust if**: PostgreSQL `idle_in_transaction_session_timeout` is lower
- **Formula**: Set to 80% of PostgreSQL idle timeout

### Environment-Specific Tuning

```bash
# Local development (1 worker)
export DATABASE_POOL_SIZE=5
export DATABASE_MAX_OVERFLOW=5

# Test environment (2 workers)
export DATABASE_POOL_SIZE=10
export DATABASE_MAX_OVERFLOW=10

# Production (4 workers)
export DATABASE_POOL_SIZE=15
export DATABASE_MAX_OVERFLOW=15
```

## Parameterized Query Security

### SQL Injection Prevention

All queries MUST use parameterized queries with SQLAlchemy `text()` and bound parameters. NEVER use string formatting (`f-strings`, `format()`, or `%`).

**Correct pattern (from repository files):**

```python
from sqlalchemy import text

# Safe: parameters bound separately
query = text("""
    SELECT run_id, mode, trigger_ref, started_at, status
    FROM fraud_gov.ops_agent_runs
    WHERE run_id = :run_id
""")
result = await session.execute(query, {"run_id": run_id})
```

**Incorrect patterns (NEVER do this):**

```python
# UNSAFE: SQL injection vulnerability
query = text(f"""
    SELECT run_id, mode, trigger_ref, started_at, status
    FROM fraud_gov.ops_agent_runs
    WHERE run_id = '{run_id}'
""")

# UNSAFE: string formatting
query = text("""
    SELECT run_id, mode, trigger_ref, started_at, status
    FROM fraud_gov.ops_agent_runs
    WHERE run_id = '{}'
""".format(run_id))
```

### Parameter Binding for JSONB

When inserting JSONB data, always use `json.dumps()` to serialize dicts:

```python
import json

query = text("""
    INSERT INTO fraud_gov.ops_agent_recommendations
        (recommendation_id, recommendation_payload)
    VALUES
        (:recommendation_id, :recommendation_payload)
""")
await session.execute(
    query,
    {
        "recommendation_id": recommendation_id,
        "recommendation_payload": json.dumps(payload_dict),  # Always serialize
    },
)
```

### Security Checklist

- [ ] All user input uses bound parameters (`:param_name` syntax)
- [ ] No string concatenation in SQL queries
- [ ] JSONB payloads serialized with `json.dumps()`
- [ ] UUID values passed as strings (asyncpg handles conversion)
- [ ] No dynamic SQL construction without parameterization

## Index Maintenance

### Key Indexes

**Performance-critical indexes** (from migration 002):

```sql
-- Investigation run lookups
CREATE INDEX idx_ops_agent_runs_status
    ON fraud_gov.ops_agent_runs(status);

CREATE INDEX idx_ops_agent_runs_started_at
    ON fraud_gov.ops_agent_runs(started_at DESC);

-- Recommendation worklist queries (keyset pagination)
CREATE INDEX idx_ops_agent_recommendations_status_created
    ON fraud_gov.ops_agent_recommendations(status, created_at DESC);

-- Transaction insight queries
CREATE INDEX idx_ops_agent_insights_transaction_id
    ON fraud_gov.ops_agent_insights(transaction_id);

CREATE INDEX idx_ops_agent_insights_generated_at
    ON fraud_gov.ops_agent_insights(generated_at DESC);

-- Audit log searches
CREATE INDEX idx_ops_agent_audit_log_entity
    ON fraud_gov.ops_agent_audit_log(entity_type, entity_id);

CREATE INDEX idx_ops_agent_audit_log_created_at
    ON fraud_gov.ops_agent_audit_log(created_at DESC);
```

### Index Usage Monitoring

Check index effectiveness with:

```sql
-- Index hit ratio (should be > 99%)
SELECT
    schemaname,
    relname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch,
    seq_scan,
    seq_tup_read
FROM pg_stat_user_tables
WHERE schemaname = 'fraud_gov'
  AND relname LIKE 'ops_agent_%'
ORDER BY seq_scan DESC;

-- Find unused indexes
SELECT
    schemaname,
    relname,
    indexrelname,
    idx_scan
FROM pg_stat_user_indexes
WHERE schemaname = 'fraud_gov'
  AND relname LIKE 'ops_agent_%'
  AND idx_scan = 0;
```

### Index Bloat Analysis

```sql
-- Check for table/index bloat
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size,
    pg_size_pretty(pg_relation_size(schemaname||'.'||tablename)) AS table_size,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename) - pg_relation_size(schemaname||'.'||tablename)) AS index_size
FROM pg_tables
WHERE schemaname = 'fraud_gov'
  AND tablename LIKE 'ops_agent_%'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

### Maintenance Routine

```sql
-- ANALYZE to update statistics (safe, non-blocking)
ANALYZE fraud_gov.ops_agent_runs;
ANALYZE fraud_gov.ops_agent_recommendations;
ANALYZE fraud_gov.ops_agent_insights;

-- VACUUM to reclaim dead tuples (autovacuum handles this)
-- Manual VACUUM ANALYZE only if performance degraded
VACUUM ANALYZE fraud_gov.ops_agent_runs;

-- REINDEX only if corruption detected (requires exclusive lock)
REINDEX INDEX CONCURRENTLY fraud_gov.idx_ops_agent_runs_status;
```

**Maintenance schedule:**
- ANALYZE: Automatic via autovacuum (or daily during low traffic)
- VACUUM: Automatic via autovacuum
- REINDEX: As needed (monitor bloat > 30%)
- Index review: Quarterly during capacity planning

## Pool Exhaustion Response

### Detection

**Symptoms:**
- Error: `sqlalchemy.exc.TimeoutError: QueuePool limit exceeded`
- Metric: `db_pool_overflow_total` increasing
- Metric: `db_pool_wait_time_seconds` > 1s

**Immediate checks:**

```python
# Check current pool utilization
from sqlalchemy.engine import Engine
from app.core.database import get_engine

engine = get_engine()
pool = engine.pool

print(f"Pool size: {pool.size()}")
print(f"Checked out connections: {pool.checkedout()}")
print(f"Overflow: {pool.overflow()}")
print(f"Available: {pool.checkedout() < pool.size()}")
```

### Response Procedure

1. **Verify pool exhaustion**
   ```sql
   -- Check active connections from ops-agent
   SELECT
       count(*),
       application_name,
       state,
       wait_event_type
   FROM pg_stat_activity
   WHERE application_name LIKE '%ops-agent%'
   GROUP BY application_name, state, wait_event_type;
   ```

2. **Identify blocking queries**
   ```sql
   -- Long-running queries blocking pool
   SELECT
       pid,
       now() - pg_stat_activity.query_start AS duration,
       query,
       state,
       wait_event_type
   FROM pg_stat_activity
   WHERE (now() - pg_stat_activity.query_start) > interval '5 minutes'
     AND application_name LIKE '%ops-agent%'
   ORDER BY duration DESC;
   ```

3. **Triage options**

   **Option A: Increase pool size (if headroom exists)**
   ```bash
   # Check PostgreSQL max_connections
   SHOW max_connections;

   # Calculate safe increase
   # current_total = 80 (10 pool + 10 overflow × 4 workers)
   # new_pool_size = min(current + 5, (max_connections - 100) / workers)

   export DATABASE_POOL_SIZE=15
   export DATABASE_MAX_OVERFLOW=15
   kubectl rollout restart deployment/ops-agent
   ```

   **Option B: Terminate blocking queries (emergency)**
   ```sql
   -- Get specific PID from long-running query check
   SELECT pg_terminate_backend(pid);
   ```

   **Option C: Scale workers (if horizontally scalable)**
   ```bash
   # More workers = more total connections
   # 4 workers × 20 connections = 80
   # 6 workers × 20 connections = 120

   kubectl scale deployment/ops-agent --replicas=6
   ```

### Prevention

- **Monitor pool metrics**: Set alert at 80% pool utilization
- **Connection timeouts**: Ensure `pool_timeout` aligns with SLA
- **Statement timeout**: 30-second limit prevents hoarding
- **Regular reviews**: Adjust pool size quarterly based on growth

## Query Optimization Patterns

### JSONB Aggregation

**Pattern from `insight_repository.py`:**

```python
# Single query with JSONB aggregation (no N+1 problem)
query = text("""
    SELECT
        i.insight_id, i.transaction_id, i.severity,
        i.insight_summary AS summary,
        i.insight_type, i.generated_at, i.model_mode,
        COALESCE(
            jsonb_agg(
                jsonb_build_object(
                    'evidence_id', e.evidence_id,
                    'evidence_kind', e.evidence_kind,
                    'evidence_payload', e.evidence_payload,
                    'created_at', e.created_at
                ) ORDER BY e.created_at ASC
            ) FILTER (WHERE e.evidence_id IS NOT NULL),
            '[]'::jsonb
        ) AS evidence
    FROM fraud_gov.ops_agent_insights i
    LEFT JOIN fraud_gov.ops_agent_evidence e ON e.insight_id = i.insight_id
    WHERE i.transaction_id = :transaction_id
    GROUP BY i.insight_id, i.transaction_id, i.severity, i.insight_summary,
             i.insight_type, i.generated_at, i.model_mode
    ORDER BY i.generated_at DESC
""")
```

**Benefits:**
- Single round-trip to database
- Avoids N+1 query problem
- Returns structured evidence nested in insight

### Keyset Pagination

**Pattern from `recommendation_repository.py`:**

```python
# Efficient cursor-based pagination
cursor_condition = """
    AND (r.status, r.created_at) < (:cursor_status, :cursor_created_at)
"""

query = text(f"""
    SELECT r.recommendation_id, r.insight_id,
           r.recommendation_type AS type, r.recommendation_payload AS payload,
           r.status, r.acknowledged_by, r.acknowledged_at, r.created_at,
           i.severity, i.insight_summary AS summary
    FROM fraud_gov.ops_agent_recommendations r
    JOIN fraud_gov.ops_agent_insights i ON i.insight_id = r.insight_id
    WHERE 1=1 {status_filter} {severity_filter} {cursor_condition}
    ORDER BY r.status ASC, r.created_at DESC
    LIMIT :limit
""")
```

**Benefits:**
- No OFFSET scan penalty
- Stable pagination (doesn't skip/duplicate rows)
- Works well with composite index `(status, created_at)`

### Idempotent Upserts

**Pattern from `insight_repository.py`:**

```python
query = text("""
    INSERT INTO fraud_gov.ops_agent_insights
        (insight_id, transaction_id, severity, insight_summary, insight_type,
         generated_at, model_mode, idempotency_key)
    VALUES
        (:insight_id, :transaction_id, :severity, :summary, :insight_type,
         :generated_at, :model_mode, :idempotency_key)
    ON CONFLICT (idempotency_key) DO UPDATE SET
        severity = EXCLUDED.severity,
        insight_summary = EXCLUDED.insight_summary,
        insight_type = EXCLUDED.insight_type,
        generated_at = EXCLUDED.generated_at,
        model_mode = EXCLUDED.model_mode
    RETURNING insight_id, transaction_id, severity, insight_summary AS summary,
              insight_type, generated_at, model_mode
""")
```

**Benefits:**
- Safe retries without duplicate inserts
- Refreshes advisory output when scoring/prompt logic changes on replay
- Atomic operation (no race conditions)
- Uses unique constraint on `idempotency_key`

### Atomic Status Updates

**Pattern from `recommendation_repository.py`:**

```python
query = text("""
    UPDATE fraud_gov.ops_agent_recommendations
    SET status = :new_status,
        acknowledged_by = :acknowledged_by,
        acknowledged_at = :acknowledged_at
    WHERE recommendation_id = :recommendation_id
      AND status = :expected_status
    RETURNING recommendation_id, insight_id,
              recommendation_type AS type, recommendation_payload AS payload,
              status, acknowledged_by, acknowledged_at, created_at
""")
```

**Benefits:**
- Compare-and-swap pattern prevents lost updates
- Returns None if status changed (concurrent modification)
- No need for explicit SELECT + UPDATE transaction

### Parallel Queries (Future Optimization)

For analytics workloads, use PostgreSQL parallel query:

```python
# Enable parallel query for large aggregations
query = text("""
    SET LOCAL max_parallel_workers_per_gather = 4;

    SELECT
        i.severity,
        COUNT(*) AS count,
        AVG(EXTRACT(EPOCH FROM (r.completed_at - r.started_at))) AS avg_duration_sec
    FROM fraud_gov.ops_agent_insights i
    JOIN fraud_gov.ops_agent_runs r ON r.trigger_ref = 'transaction:' || i.transaction_id
    WHERE i.generated_at > NOW() - INTERVAL '30 days'
    GROUP BY i.severity
""")
```

## Monitoring

### Key Database Metrics

**Connection pool metrics:**
```python
# Exposed in app/core/metrics.py
- db_pool_size_total: Current pool size
- db_pool_overflow_total: Current overflow connections
- db_pool_wait_time_seconds: Time waiting for connection
- db_query_duration_seconds: Query execution time (by table)
```

**PostgreSQL metrics (via exporter):**
```yaml
# pg_stat_statements counters
- pg_stat_activity_count: Active connections by state
- pg_stat_statements_calls_total: Query execution count
- pg_stat_statements_total_time_seconds: Total query time
- pg_stat_statements_mean_time_seconds: Avg query time
```

### Alerting Queries

```sql
-- Alert: Long-running queries (> 30 seconds)
SELECT
    pid,
    now() - query_start AS duration,
    substring(query, 1, 100) AS query_preview
FROM pg_stat_activity
WHERE datname = 'fraud_gov'
  AND now() - query_start > interval '30 seconds'
  AND state != 'idle'
  AND application_name LIKE '%ops-agent%';

-- Alert: High lock contention
SELECT
    pid,
    usename,
    pg_blocking_pids(pid) AS blocked_by,
    query as blocked_query
FROM pg_stat_activity
WHERE cardinality(pg_blocking_pids(pid)) > 0;

-- Alert: Transaction bloat
SELECT
    schemaname,
    tablename,
    n_dead_tup,
    n_live_tup,
    round(100 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'fraud_gov'
  AND tablename LIKE 'ops_agent_%'
  AND round(100 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) > 10;
```

### Performance Baselines

**Expected query performance:**

| Query | Target P95 | Index Used |
|-------|-----------|------------|
| Get run by ID | < 10ms | `idx_ops_agent_runs_status` + PK |
| List recommendations (50) | < 50ms | `idx_ops_agent_recommendations_status_created` |
| Get insights with evidence | < 100ms | `idx_ops_agent_insights_transaction_id` |
| Update recommendation status | < 20ms | PK lookup |
| Insert investigation run | < 50ms | PK constraint |

**Investigation pipeline database budget:**
- Deterministic mode: < 200ms total DB time
- LLM mode: < 500ms total DB time
- LLM time excluded (external API call)

## Troubleshooting

### Issue: Connection Timeout Errors

**Error:**
```
sqlalchemy.exc.TimeoutError: QueuePool limit exceeded
```

**Diagnosis:**
1. Check pool utilization metrics
2. Verify pool size vs worker count
3. Check for long-running queries blocking pool

**Solutions:**
- Increase `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW`
- Reduce query execution time (add indexes, optimize queries)
- Scale horizontally (add workers if DB has headroom)
- Reduce statement timeout to fail fast (protects pool)

### Issue: Slow Query Performance

**Symptoms:**
- API latency P95 > baseline
- `db_query_duration_seconds` increasing
- `pg_stat_statements` shows high mean query time

**Diagnosis:**
```sql
-- Find slow queries
SELECT
    query,
    calls,
    total_exec_time / 1000 AS total_seconds,
    mean_exec_time / 1000 AS mean_seconds,
    stddev_exec_time / 1000 AS stddev_seconds
FROM pg_stat_statements
WHERE query LIKE '%ops_agent_%'
ORDER BY mean_exec_time DESC
LIMIT 10;

-- Check query plan (EXPLAIN ANALYZE)
EXPLAIN ANALYZE
SELECT * FROM fraud_gov.ops_agent_recommendations
WHERE status = 'OPEN'
ORDER BY created_at DESC
LIMIT 50;
```

**Solutions:**
- Add missing indexes (use query plan to identify)
- Rewrite queries to use indexes (avoid functions on indexed columns)
- Use `ANALYZE` to update statistics
- Consider partitioning for large historical tables

### Issue: Lock Contention

**Symptoms:**
- Queries waiting on locks
- `pg_blocking_pids()` shows blocked transactions
- Throughput degradation

**Diagnosis:**
```sql
-- Identify blocking queries
SELECT
    blocked_locks.pid AS blocked_pid,
    blocked_activity.usename AS blocked_user,
    blocking_locks.pid AS blocking_pid,
    blocking_activity.usename AS blocking_user,
    blocked_activity.query AS blocked_statement,
    blocking_activity.query AS blocking_statement
FROM pg_catalog.pg_locks blocked_locks
JOIN pg_catalog.pg_stat_activity blocked_activity
  ON blocked_activity.pid = blocked_locks.pid
JOIN pg_catalog.pg_locks blocking_locks
  ON blocking_locks.locktype = blocked_locks.locktype
  AND blocking_locks.DATABASE IS NOT DISTINCT FROM blocked_locks.DATABASE
  AND blocking_locks.relation IS NOT DISTINCT FROM blocked_locks.relation
  AND blocking_locks.page IS NOT DISTINCT FROM blocked_locks.page
  AND blocking_locks.tuple IS NOT DISTINCT FROM blocked_locks.tuple
  AND blocking_locks.virtualxid IS NOT DISTINCT FROM blocked_locks.virtualxid
  AND blocking_locks.transactionid IS NOT DISTINCT FROM blocked_locks.transactionid
  AND blocking_locks.classid IS NOT DISTINCT FROM blocked_locks.classid
  AND blocking_locks.objid IS NOT DISTINCT FROM blocked_locks.objid
  AND blocking_locks.objsubid IS NOT DISTINCT FROM blocked_locks.objsubid
  AND blocking_locks.pid != blocked_locks.pid
JOIN pg_catalog.pg_stat_activity blocking_activity
  ON blocking_activity.pid = blocking_locks.pid
WHERE NOT blocked_locks.GRANTED;
```

**Solutions:**
- Keep transactions short (commit quickly)
- Avoid long-running transactions in request handlers
- Use advisory locks for application-level coordination
- Terminate blocking queries if hung (emergency only)

### Issue: Table Bloat

**Symptoms:**
- Disk usage growing despite fixed row count
- Query performance degrading over time
- `pg_stat_user_tables` shows high dead tuple ratio

**Diagnosis:**
```sql
-- Check bloat ratio
SELECT
    schemaname,
    tablename,
    n_dead_tup,
    n_live_tup,
    round(100 * n_dead_tup / NULLIF(n_live_tup + n_dead_tup, 0), 2) AS dead_ratio
FROM pg_stat_user_tables
WHERE schemaname = 'fraud_gov'
  AND tablename LIKE 'ops_agent_%'
ORDER BY dead_ratio DESC;
```

**Solutions:**
- Ensure autovacuum is running (`SHOW autovacuum;`)
- Tune autovacuum thresholds for high-traffic tables
- Run manual `VACUUM ANALYZE` during maintenance window
- Consider `VACUUM FULL` for severe bloat (requires exclusive lock)

### Issue: Out of Memory Errors

**Error:**
```
psycopg2.operationalerror: out of memory
DETAIL: Failed on request of size N.
```

**Diagnosis:**
```sql
-- Check work_mem setting
SHOW work_mem;

-- Find memory-intensive queries
SELECT
    query,
    calls,
    total_exec_time,
    mean_exec_time,
    rows,
    100.0 * shared_blks_hit / NULLIF(shared_blks_hit + shared_blks_read, 0) AS hit_percent
FROM pg_stat_statements
WHERE query LIKE '%ops_agent_%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

**Solutions:**
- Increase `work_mem` (affects sorting, hashing)
- Rewrite queries to use less memory (avoid large sorts)
- Add indexes to avoid sorts
- Use cursor-based pagination instead of large LIMIT

### Issue: Statement Timeout Fires

**Error:**
```
sqlalchemy.exc.DBAPIError: (sqlalchemy.dialects.postgresql.asyncpg.Error) canceling statement due to statement timeout
```

**Diagnosis:**
- Statement timeout set to 30 seconds in `database.py`
- Query execution exceeded timeout

**Solutions:**
- Identify slow query (check logs for `statement_timeout`)
- Optimize query or add indexes
- Increase timeout if query is legitimately complex
- Break large query into smaller chunks

## Emergency Procedures

### Pool Exhaustion (SEV2)

1. **Verify impact**: Check error rate for pool timeout errors
2. **Check blocking queries**: Look for long-running transactions
3. **Terminate blockers**: If critical, `pg_terminate_backend()` blocking PIDs
4. **Scale pool**: Increase `DATABASE_POOL_SIZE` if headroom exists
5. **Scale workers**: Add worker pods if horizontally scalable
6. **Post-incident**: Review query patterns, add indexes

### Database Degradation (SEV1)

1. **Check PostgreSQL health**: `pg_isready`, connection counts
2. **Review resource usage**: CPU, memory, disk I/O
3. **Check for locks**: Look for blocking transactions
4. **Kill long queries**: Terminate queries running > 5 minutes
5. **Enable read-only mode**: If service is degrading, disable writes
6. **Failover**: If primary DB is unhealthy, trigger failover

### Data Corruption (SEV0)

1. **Stop writes**: Disable all mutation endpoints
2. **Verify corruption**: `REINDEX TABLE CONCURRENTLY` check
3. **Restore backup**: PITR to last known good state
4. **Verify restore**: Check row counts, checksums
5. **Resume service**: Gradually re-enable traffic
6. **Post-mortem**: Identify root cause (hardware, software, operator error)

## References

- **Schema**: `db/migrations/001_create_ops_agent_tables.sql`
- **Indexes**: `db/migrations/002_create_ops_agent_indexes.sql`
- **Database code**: `app/core/database.py`, `app/persistence/*.py`
- **Configuration**: `app/core/config.py` (DatabaseConfig)
- **Runbooks**: `docs/06-operations/runbooks.md`
- **Performance**: `docs/06-operations/performance-baselines.md`
