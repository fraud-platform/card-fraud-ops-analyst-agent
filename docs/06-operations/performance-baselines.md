# Performance Baselines

This document establishes performance baselines for the Card Fraud Ops Analyst Agent. These baselines are used for monitoring, alerting, and capacity planning. All measurements are from production-like environments with realistic data volumes.

## Overview

| Metric | Baseline (P50) | Baseline (P95) | Max Threshold |
|--------|---------------|----------------|---------------|
| End-to-end investigation (agentic fallback path) | < 200ms | < 500ms | 2s |
| End-to-end investigation (LLM) | < 60s | < 90s | 120s |
| GET /investigations/{id} | < 20ms | < 50ms | 100ms |
| GET /transactions/{id}/insights | < 15ms | < 30ms | 50ms |
| GET /worklist/recommendations | < 20ms | < 50ms | 100ms |
| POST /worklist/recommendations/{id}/acknowledge | < 20ms | < 40ms | 100ms |

## Pipeline Stage Latency Breakdown

### 1. Context Build Stage

**Purpose**: Extract transaction context from fraud_gov database

| Component | Baseline | Target | Max Threshold |
|-----------|----------|--------|---------------|
| Transaction lookup (fraud_gov.transactions) | < 10ms | < 15ms | 30ms |
| Rule matches lookup (transaction_rule_matches) | < 10ms | < 15ms | 30ms |
| Reviews lookup (transaction_reviews) | < 5ms | < 10ms | 20ms |
| Notes lookup (analyst_notes) | < 5ms | < 10ms | 20ms |
| Context construction | < 20ms | < 50ms | 100ms |

**Total**: < 50ms (P95), < 100ms (max)

**Key Queries**:
```sql
-- Transaction lookup (primary)
SELECT id, transaction_id, card_id, transaction_amount, decision
FROM fraud_gov.transactions
WHERE id = $1;

-- Rule matches join
SELECT trm.rule_name, trm.rule_action, trm.match_score
FROM fraud_gov.transaction_rule_matches trm
WHERE trm.transaction_id = $1;
```

**Optimization Notes**:
- Index on `transactions.id` (UUID primary key)
- Index on `transaction_rule_matches.transaction_id`
- Use connection pooling (10 base + 10 overflow)

---

### 2. Pattern Analysis Stage

**Purpose**: Detect fraud patterns using rule-based analysis

| Component | Baseline | Target | Max Threshold |
|-----------|----------|--------|---------------|
| Velocity pattern detection | < 10ms | < 20ms | 50ms |
| Geographic pattern detection | < 10ms | < 20ms | 50ms |
| Amount anomaly detection | < 5ms | < 10ms | 20ms |
| Pattern scoring aggregation | < 10ms | < 20ms | 40ms |

**Total**: < 35ms (P95), < 100ms (max)

**Optimization Notes**:
- All patterns computed in-memory (no DB queries)
- Pre-computed velocity snapshots from TM
- O(1) lookups for pattern rules

---

### 3. Similarity Analysis Stage

**Purpose**: Find semantically similar historical transactions using vector search

| Mode | Baseline | Target | Max Threshold |
|------|----------|--------|---------------|
| With vector search (pgvector) | < 100ms | < 200ms | 500ms |
| Stub/disabled mode | < 5ms | < 10ms | 20ms |
| Embedding generation (Ollama) | < 500ms | < 1000ms | 2000ms |

**Total**: < 150ms (P95) with vector search, < 10ms (P95) stub

**Key Queries**:
```sql
-- Vector similarity search (pgvector)
SELECT t.id, t.transaction_id, t.decision,
       te.embedding <=> $1 as distance
FROM fraud_gov.transactions t
JOIN fraud_gov.ops_agent_transaction_embeddings te ON t.id = te.transaction_id
WHERE te.created_at > NOW() - INTERVAL '90 days'
  AND t.decision IN ('DECLINE', 'REVIEW')
ORDER BY distance
LIMIT 20;
```

**Optimization Notes**:
- IVFFlat index on `embedding` column (1024 dimensions)
- Time window filter (90 days) reduces search space
- Cosine distance operator (`<=>`)
- Embedding generation is cached per transaction

**Configuration**:
```bash
VECTOR_ENABLED=true
VECTOR_MODEL_NAME=mxbai-embed-large
VECTOR_DIMENSION=1024
VECTOR_SEARCH_LIMIT=20
VECTOR_TIME_WINDOW_DAYS=90
VECTOR_MIN_SIMILARITY=0.3
```

---

### 4. LLM Reasoning Stage

**Purpose**: Generate narrative explanation using LLM

| Provider | Baseline | Target | Max Threshold |
|----------|----------|--------|---------------|
| Ollama Cloud (`gpt-oss:20b`) | < 20s | < 40s | 60s |
| Ollama local (fallback environment only) | < 30s | < 60s | 90s |
| Rule-sequence fallback | < 50ms | < 100ms | 200ms |

**Total**: < 40s (P95) with Ollama Cloud, < 60s (P95) with local fallback environment

**Optimization Notes**:
- Retry logic: bounded retries via `LLM_MAX_RETRIES` (default 1)
- Timeout per request: 30s
- JSON mode enabled for structured output
- Prompt size limited to 4000 tokens
- Caching: LLM responses cached for 24 hours

**Fallback Behavior**:
1. LLM timeout → retry with same provider
2. LLM error -> bounded retry (LLM_MAX_RETRIES)
3. All retries failed → fall back to evidence-only mode

**Configuration**:
```bash
LLM_PROVIDER=ollama/gpt-oss:20b
LLM_TIMEOUT=30
LLM_MAX_RETRIES=1
LLM_BASE_URL=https://ollama.com
LLM_MAX_PROMPT_TOKENS=4000
```

---

### 5. Recommendation Generation Stage

**Purpose**: Generate actionable recommendations based on evidence

| Component | Baseline | Target | Max Threshold |
|-----------|----------|--------|---------------|
| Recommendation scoring | < 10ms | < 20ms | 50ms |
| Conflict matrix computation | < 20ms | < 50ms | 100ms |
| Explanation builder | < 20ms | < 50ms | 100ms |
| Freshness weighting | < 10ms | < 20ms | 40ms |
| Recommendation serialization | < 10ms | < 20ms | 40ms |

**Total**: < 70ms (P95), < 200ms (max)

**Optimization Notes**:
- Conflict matrix is O(n²) where n = evidence count (typically < 20)
- Freshness weighting is O(n) with simple exponential decay
- Explanation builder is rule-based text synthesis

**Configuration**:
```bash
OPS_AGENT_CONFLICT_MATRIX_ENABLED=false  # Optional feature
OPS_AGENT_EXPLANATION_BUILDER_ENABLED=false  # Optional feature
OPS_AGENT_FRESHNESS_ENABLED=true
```

---

### 6. Persistence Stage

**Purpose**: Save investigation run, insights, recommendations to database

| Component | Baseline | Target | Max Threshold |
|-----------|----------|--------|---------------|
| Insert ops_agent_runs | < 20ms | < 40ms | 100ms |
| Insert ops_agent_insights | < 15ms | < 30ms | 80ms |
| Insert ops_agent_recommendations | < 15ms | < 30ms | 80ms |
| Insert ops_agent_audit_log | < 10ms | < 20ms | 50ms |

**Total**: < 60ms (P95), < 200ms (max)

**Key Queries**:
```sql
-- Insert investigation run
INSERT INTO fraud_gov.ops_agent_runs
(run_id, trigger_ref, status, mode, evidence_payload, created_at)
VALUES ($1, $2, $3, $4, $5, NOW());

-- Insert insight
INSERT INTO fraud_gov.ops_agent_insights
(insight_id, run_id, insight_summary, evidence_payload, created_at)
VALUES ($1, $2, $3, $4, NOW());

-- Insert recommendation
INSERT INTO fraud_gov.ops_agent_recommendations
(recommendation_id, run_id, transaction_id, recommendation_type, recommendation_payload, created_at)
VALUES ($1, $2, $3, $4, $5, NOW());
```

**Optimization Notes**:
- Use prepared statements (via SQLAlchemy core)
- Batch inserts where possible
- JSONB columns for flexible payloads
- Asyncpg for non-blocking I/O

---

## Database Query Performance

### Read Queries

| Query | Baseline (P95) | Target | Index Used |
|-------|---------------|--------|------------|
| Get transaction by ID | < 10ms | < 20ms | PRIMARY KEY |
| Get investigation run by ID | < 15ms | < 30ms | `idx_runs_run_id` |
| Get insights by run_id | < 20ms | < 40ms | `idx_insights_run_id` |
| Get recommendations by status | < 30ms | < 50ms | `idx_recommendations_status` |
| Vector similarity search | < 100ms | < 200ms | `idx_embeddings_vector` |
| Get audit log by run_id | < 20ms | < 40ms | `idx_audit_log_run_id` |

### Write Queries

| Query | Baseline (P95) | Target | Notes |
|-------|---------------|--------|-------|
| Insert investigation run | < 20ms | < 40ms | Single row |
| Insert insight | < 15ms | < 30ms | Single row |
| Insert recommendation | < 15ms | < 30ms | Single row |
| Insert audit log entry | < 10ms | < 20ms | Single row |
| Update recommendation status | < 20ms | < 40ms | Row-level lock |
| Update investigation status | < 20ms | < 40ms | Row-level lock |

---

## Connection Pool Metrics

### Configuration

```python
pool_size = 10          # Base connections
max_overflow = 10       # Additional connections under load
pool_timeout = 30       # Seconds to wait for connection
pool_recycle = 1800     # Recycle connections after 30 minutes
```

### Per-Worker Pool (4 workers)

| Metric | Value | Notes |
|--------|-------|-------|
| Base connections | 10 per worker | 40 total |
| Max overflow | 10 per worker | 40 overflow |
| Total max connections | 80 | < server limit of 100 |
| Recommended max | 80 | Leave 20 for admin/reporting |

### Pool Utilization Baselines

| Utilization | Status | Action |
|-------------|--------|--------|
| < 50% | Healthy | No action |
| 50-80% | Normal | Monitor |
| 80-95% | Warning | Investigate slow queries |
| > 95% | Critical | Increase pool or scale workers |

---

## API Endpoint Performance

### POST /api/v1/ops-agent/investigations/run

**Purpose**: Create new investigation for a transaction

| Mode | Baseline (P95) | Target | Max Threshold |
|------|---------------|--------|---------------|
| Fallback path | < 300ms | < 500ms | 2s |
| LLM (Ollama) | < 60s | < 90s | 120s |
| LLM (Cloud) | < 40s | < 60s | 90s |

**Breakdown**:
- Context build: ~50ms
- Pattern analysis: ~35ms
- Similarity search: ~150ms (with vector) or ~10ms (stub)
- LLM reasoning: ~30s (Ollama) or ~20s (cloud) or ~100ms (fallback path)
- Recommendation generation: ~70ms
- Persistence: ~60ms

---

### GET /api/v1/ops-agent/investigations/{investigation_id}

**Purpose**: Retrieve investigation details

| Component | Baseline (P95) | Target | Max Threshold |
|-----------|---------------|--------|---------------|
| Database lookup | < 20ms | < 40ms | 100ms |
| Insight serialization | < 10ms | < 20ms | 50ms |
| Recommendation serialization | < 10ms | < 20ms | 50ms |

**Total**: < 40ms (P95), < 150ms (max)

---

### GET /api/v1/ops-agent/transactions/{transaction_id}/insights

**Purpose**: Get insights for a transaction

| Component | Baseline (P95) | Target | Max Threshold |
|-----------|---------------|--------|---------------|
| Database lookup | < 15ms | < 30ms | 80ms |
| Evidence serialization | < 10ms | < 20ms | 50ms |

**Total**: < 25ms (P95), < 100ms (max)

---

### GET /api/v1/ops-agent/worklist/recommendations

**Purpose**: Get recommendation worklist with pagination

| Component | Baseline (P95) | Target | Max Threshold |
|-----------|---------------|--------|---------------|
| Database query (paginated) | < 30ms | < 50ms | 100ms |
| Severity join | < 10ms | < 20ms | 50ms |
| Response serialization | < 10ms | < 20ms | 50ms |

**Total**: < 40ms (P95), < 150ms (max)

**Query**:
```sql
SELECT r.recommendation_id, r.transaction_id, r.recommendation_type,
       r.recommendation_payload, r.status, r.priority, r.created_at
FROM fraud_gov.ops_agent_recommendations r
WHERE r.status = 'OPEN'
ORDER BY r.priority DESC, r.created_at ASC
LIMIT $1 OFFSET $2;
```

---

### POST /api/v1/ops-agent/worklist/recommendations/{id}/acknowledge

**Purpose**: Acknowledge a recommendation

| Component | Baseline (P95) | Target | Max Threshold |
|-----------|---------------|--------|---------------|
| Database update | < 20ms | < 40ms | 100ms |
| Audit log insert | < 10ms | < 20ms | 50ms |

**Total**: < 30ms (P95), < 120ms (max)

---

## Alerting Thresholds

### Investigation Latency Alerts

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| Fallback path P95 | > 1s | > 2s | 15 min |
| LLM P95 | > 120s | > 180s | 15 min |
| Any stage P95 | > 2× baseline | > 5× baseline | 15 min |

### Error Rate Alerts

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| 5xx error ratio | > 2% | > 5% | 10 min |
| 4xx error ratio | > 5% | > 10% | 15 min |
| DB connection error ratio | > 1% | > 3% | 5 min |
| LLM failure ratio | > 10% | > 25% | 15 min |

### Resource Utilization Alerts

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| DB pool utilization | > 80% | > 95% | 5 min |
| Worker CPU usage | > 70% | > 90% | 10 min |
| Memory usage per worker | > 1GB | > 2GB | 10 min |
| Recommendation queue depth | > 1000 | > 5000 | 10 min |

### Business Logic Alerts

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| Investigation rate (per minute) | < 1 | = 0 | 15 min |
| Recommendation queue age | > 1 day | > 7 days | 30 min |
| Duplicate investigation (409) ratio | > 5% | > 10% | 15 min |
| Investigation not found (404) ratio | > 1% | > 3% | 15 min |

---

## Performance Testing

### Load Testing Baselines

**Tool**: `k6` or `locust`

**Scenario 1: Normal Load**
- Requests per second: 10
- Duration: 10 minutes
- Expected P95 latency: < 500ms (fallback path)
- Error rate: < 1%

**Scenario 2: Peak Load**
- Requests per second: 50
- Duration: 5 minutes
- Expected P95 latency: < 2s (fallback path)
- Error rate: < 2%

**Scenario 3: Stress Test**
- Requests per second: 100
- Duration: 2 minutes
- Expected: System degrades gracefully, returns 503 when overloaded
- Connection pool exhaustion expected

### Performance Test Commands

```bash
# Run load test with k6
k6 run --vus 10 --duration 10s scripts/load_test.js

# Run database performance test
uv run pytest tests/performance/test_db_query_performance.py -v

# Generate HTML report
uv run pytest tests/ --html=htmlcov/performance.html --self-contained-html
```

---

## Monitoring and Observability

### Key Metrics to Track

1. **Pipeline Stage Latency**: `ops_agent_pipeline_stage_duration_seconds{stage}`
2. **Investigation Latency**: `ops_agent_investigation_latency_seconds{mode}`
3. **Database Query Latency**: `ops_agent_db_query_duration_seconds{query_name}`
4. **LLM Request Latency**: `ops_agent_llm_request_duration_seconds{provider}`
5. **Connection Pool Utilization**: `ops_agent_db_pool_utilization`
6. **Error Rates**: `ops_agent_errors_total{error_type, dependency}`

### Dashboards

**Recommended Grafana Dashboards**:
1. Ops Agent Overview (investigation rate, latency, errors)
2. Pipeline Performance (per-stage breakdown)
3. Database Performance (query latency, pool utilization)
4. LLM Performance (request latency, failure rate, token usage)
5. Business Metrics (recommendation queue, acknowledgment rate)

### Traces

**Key Spans to Trace**:
- `POST /investigations/run` (root span)
  - `context_builder.build_context`
  - `pattern_engine.analyze_patterns`
  - `similarity_engine.find_similar_transactions`
  - `reasoning_engine.generate_narrative`
  - `recommendation_engine.generate_recommendations`
  - `database.insert_investigation`

**View Traces**: http://localhost:16686 (Jaeger UI)

---

## Performance Optimization Checklist

### Database Optimization
- [ ] Verify all foreign keys have indexes
- [ ] Analyze query execution plans (`EXPLAIN ANALYZE`)
- [ ] Review slow query log weekly
- [ ] Update table statistics (`ANALYZE ops_agent_runs`)
- [ ] Monitor index bloat (`pg_stat_user_tables`)

### Application Optimization
- [ ] Profile code with `cProfile` for slow functions
- [ ] Review async/await usage (avoid blocking calls)
- [ ] Optimize serialization (Pydantic model tuning)
- [ ] Cache frequently accessed data (embeddings, LLM responses)
- [ ] Use connection pooling correctly (release connections promptly)

### LLM Optimization
- [ ] Use appropriate model size (3B for dev, Sonnet for prod)
- [ ] Limit prompt size (< 4000 tokens)
- [ ] Enable JSON mode for structured output
- [ ] Cache responses for similar requests
- [ ] Implement exponential backoff for retries

### Infrastructure Optimization
- [ ] Right-size worker count (4 workers for normal load)
- [ ] Tune connection pool (10 base + 10 overflow)
- [ ] Use PgBouncer for connection pooling
- [ ] Enable HTTP/2 for external API calls
- [ ] Use CDN for static content (if any)

---

## Related Documentation

- [Observability](./observability.md)
- [Runbooks](./runbooks.md)
- [Architecture](../02-development/architecture.md)
- [Testing Strategy](../04-testing/testing-strategy.md)
