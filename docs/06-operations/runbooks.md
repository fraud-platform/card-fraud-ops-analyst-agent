# Operational Runbooks

This document provides step-by-step procedures for common operational scenarios. Each scenario includes symptoms, diagnosis steps, resolution actions, and prevention strategies.

## Quick Reference

| Scenario | Severity | First Action | Escalation |
|----------|----------|--------------|------------|
| Investigation pipeline failure | SEV2 | Check feature flags, enable fallback mode | Platform team |
| Database connection exhaustion | SEV2 | Check pool metrics, restart workers if needed | DBA team |
| LLM service degradation | SEV3 | Enable fallback mode, check provider status | LLM provider |
| High latency investigations | SEV3 | Review traces, check vector search | N/A |
| Auth0/JWKS validation failures | SEV2 | Verify JWKS URL, check token issuer | Security team |
| Investigation not found (404) | SEV3 | Check timing, verify DB state | N/A |
| Duplicate investigation (409) | SEV3 | Review trigger_ref, check for race condition | N/A |

## Container Context (Platform Group)

In local/shared platform environments, Ops Agent runs as the `ops-agent` container in
`card-fraud-platform` using `docker-compose.yml` + `docker-compose.apps.yml` with `--profile apps`.

```bash
# From card-fraud-platform
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps ps ops-agent
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps logs -f ops-agent
```

Use these commands when reproducing operational issues locally. Kubernetes commands in this runbook
apply to cluster deployments only.

Default platform posture:
- Keep `OPS_AGENT_ENABLE_LLM_REASONING=true` and `VECTOR_ENABLED=true` in normal operation.
- Use feature-flag disablement only as a time-bound incident mitigation with explicit on-call approval.

## Common Operational Scenarios

### 1. Investigation Pipeline Failure

**Symptoms:**
- `POST /api/v1/ops-agent/investigations/run` returns 500 or 503
- Error logs showing `OpsAgentError` variants
- Metrics spike in `ops_agent_dependency_failures_total`

**Diagnosis:**
```bash
# Check recent errors
grep "ERROR" /var/log/ops-agent/app.log | tail -50

# Verify feature flags
# Agentic runtime feature flags
doppler secrets get OPS_AGENT_ENABLE_LLM_REASONING

# Check database connectivity
psql $DATABASE_URL_APP -c "SELECT 1"

# View recent traces
jaeger: http://localhost:16686
# Filter by operation name: "POST /api/v1/ops-agent/investigations/run"
```

**Resolution Actions:**

1. **If LLM reasoning is failing (temporary mitigation only):**
   ```bash
   # Disable LLM reasoning, fall back to evidence-only mode
   doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=false
   # Restart service for settings to take effect
   kubectl rollout restart deployment/ops-agent
   ```

2. **If vector search is failing (temporary mitigation only):**
   ```bash
   # Disable vector similarity search
   doppler secrets set VECTOR_ENABLED=false
   kubectl rollout restart deployment/ops-agent
   ```

3. **If database connection is failing:**
   See "Database Connection Issues" section below.

4. **If rule draft export is failing:**
   ```bash
   # Disable rule draft export (analysts can still create drafts manually)
   doppler secrets set OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT=false
   kubectl rollout restart deployment/ops-agent
   ```

**Prevention:**
- Keep `OPS_AGENT_ENABLE_LLM_REASONING=true` and `VECTOR_ENABLED=true` in normal operation; only disable temporarily during incidents.
- Monitor `ops_agent_dependency_failures_total` by dependency type
- Set up alerts for error ratio > 2% for 10 minutes

---

### 2. Database Connection Pool Exhaustion

**Symptoms:**
- `OperationalError: server closed the connection unexpectedly`
- `TimeoutError: pool timeout expired` (30s default)
- Metrics showing pool utilization near 100%

**Diagnosis:**
```sql
-- Check active connections from ops-agent
SELECT count(*), state
FROM pg_stat_activity
WHERE usename = 'ops_agent_app'
GROUP BY state;

-- Check for blocked queries
SELECT pid, now() - query_start as duration, query
FROM pg_stat_activity
WHERE usename = 'ops_agent_app'
  AND state = 'active'
  AND now() - query_start > interval '5 seconds';
```

**Resolution Actions:**

1. **Immediate (if critical):**
   ```bash
   # Increase pool size temporarily
   doppler secrets set DATABASE_POOL_SIZE=15  # default 10
   doppler secrets set DATABASE_MAX_OVERFLOW=15  # default 10
   kubectl rollout restart deployment/ops-agent
   ```
   Local platform alternative:
   ```bash
   doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile apps up -d ops-agent
   ```

   Important:
   - Do not add pool settings into `DATABASE_URL_*` query strings.
   - Set pool values via `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` environment variables.

2. **Root cause analysis:**
   - Check for long-running queries in traces
   - Verify connection recycling is working (1800s default)
   - Review worker count (4 workers × 20 connections = 80 max)

3. **Long-term:**
   - Optimize slow queries (see Performance Baselines)
   - Consider PgBouncer for connection pooling if needed

**Prevention:**
- Set up alert for pool utilization > 80% for 5 minutes
- Use connection pooling middleware (PgBouncer) in production
- Regularly review query performance in traces

---

### 3. LLM Service Degradation

**Symptoms:**
- Investigations taking > 90 seconds (LLM timeout is 30s with bounded retries)
- Errors: `httpx.HTTPStatusError`, `TimeoutError`
- Metrics: `ops_agent_dependency_failures_total{dependency_type="llm"}`

**Diagnosis:**
```bash
# Check LLM provider status
doppler secrets get LLM_PROVIDER

# Test provider connectivity
printf "Authorization: Bearer %s\n" "$LLM_API_KEY" > /tmp/ops_agent_llm_header
curl -H @/tmp/ops_agent_llm_header "$LLM_BASE_URL/api/tags"
rm -f /tmp/ops_agent_llm_header

# View LLM error logs
grep "LLM" /var/log/ops-agent/app.log | grep -i "error\|timeout" | tail -20
```

**Resolution Actions:**

1. **Enable fallback mode:**
   ```bash
   doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=false
   kubectl rollout restart deployment/ops-agent
   # Service will use evidence-only fallback mode (no LLM calls)
   ```

2. **Validate Ollama endpoint connectivity:**
   ```bash
   printf "Authorization: Bearer %s\n" "$LLM_API_KEY" > /tmp/ops_agent_llm_header
   curl -H @/tmp/ops_agent_llm_header "$LLM_BASE_URL/api/tags"
   rm -f /tmp/ops_agent_llm_header
   ```

3. **If authentication fails:**
   - Verify `LLM_API_KEY` is set and valid
   - Verify `LLM_PROVIDER` uses `ollama/...` or `ollama_chat/...`
   - Verify `LLM_BASE_URL` points to Ollama Cloud, not localhost

**Prevention:**
- Monitor `ops_agent_investigation_latency_seconds{mode="llm"}`
- Set up alert for P95 > 60s for 15 minutes
- Use fallback mode for critical operations

---

### 4. High Latency Investigations

**Symptoms:**
- `POST /investigations/run` taking > 2 seconds (fallback path) or > 90s (LLM)
- Analyst complaints about slow investigations
- Metrics: `ops_agent_investigation_latency_seconds` P95 above baseline

**Diagnosis:**
```bash
# View recent traces in Jaeger
# http://localhost:16686
# Look for slow spans in investigation pipeline

# Check which stage is slow
grep "pipeline_stage" /var/log/ops-agent/app.log | grep "duration_ms" | tail -50

# Check vector search latency
grep "similarity_search" /var/log/ops-agent/app.log | grep "duration_ms" | tail -20

# Check database query performance
SELECT query, mean_exec_time, calls
FROM pg_stat_statements
WHERE query LIKE '%ops_agent%'
ORDER BY mean_exec_time DESC
LIMIT 10;
```

**Resolution Actions:**

1. **If context building is slow (> 100ms):**
   - Check TM API response time
   - Verify `fraud_gov` query performance
   - Consider caching for frequently accessed transactions

2. **If similarity search is slow (> 200ms):**
   - Verify pgvector index exists on `transaction_embeddings`
   - Check embedding service latency
   - Reduce `VECTOR_SEARCH_LIMIT` (default 20)

3. **If LLM reasoning is slow (> 60s):**
   - Check LLM provider response time
   - Consider smaller prompt (`LLM_MAX_PROMPT_TOKENS`)
   - Enable fallback mode

4. **If recommendation generation is slow (> 100ms):**
   - Check conflict matrix computation (if enabled)
   - Verify explanation builder is not hitting rate limits

**Prevention:**
- Monitor each pipeline stage latency separately
- Set up alerts for each stage exceeding baseline
- Regular performance reviews (weekly)

---

### 5. Investigation Not Found (404)

**Symptoms:**
- `GET /api/v1/ops-agent/investigations/{investigation_id}` returns 404
- Error: "Investigation not found"

**Diagnosis:**
```sql
-- Check if investigation exists in database
SELECT run_id, status, created_at
FROM fraud_gov.ops_agent_runs
WHERE run_id = '<run_id_from_error>';

-- Check if transaction exists
SELECT id, transaction_id, decision
FROM fraud_gov.transactions
WHERE id = '<transaction_id>';

-- Check application logs for race conditions
grep "session committed" /var/log/ops-agent/app.log | tail -20
```

**Resolution Actions:**

1. **If investigation was just created:**
   - Wait 2-3 seconds and retry (timing race between commit and next request)
   - This is a known issue with fast LLM responses (< 5s)

2. **If investigation truly doesn't exist:**
   - Check if request failed during creation
   - Verify transaction ID is valid
   - Re-submit investigation request

**Prevention:**
- Add retry logic in client (exponential backoff)
- Use `POST /investigations/run` response body for immediate follow-up
- Monitor 404 rate for investigations (should be < 1%)

---

### 6. Duplicate Investigation (409 Conflict)

**Symptoms:**
- `POST /api/v1/ops-agent/investigations/run` returns 409
- Error: "Investigation already exists for transaction"
- Response includes existing `run_id`

**Diagnosis:**
```sql
-- Check for existing investigation
SELECT run_id, trigger_ref, status, created_at
FROM fraud_gov.ops_agent_runs
WHERE trigger_ref = '<transaction_id>';

-- Check for retry storms in logs
grep "409" /var/log/ops-agent/app.log | tail -20
```

**Resolution Actions:**

1. **Use existing investigation:**
   ```bash
   # Get existing run_id from 409 response
   # Avoid placing raw bearer tokens directly in command-line arguments
   AUTH_HEADER_FILE="$(mktemp)"
   chmod 600 "$AUTH_HEADER_FILE"
   trap 'rm -f "$AUTH_HEADER_FILE"' EXIT
   printf "Authorization: Bearer %s\n" "$TOKEN" > "$AUTH_HEADER_FILE"
   curl -H @"$AUTH_HEADER_FILE" \
     "https://api.example.com/api/v1/ops-agent/investigations/$EXISTING_RUN_ID"
   rm -f "$AUTH_HEADER_FILE"
   trap - EXIT
   ```

2. **If re-investigation is needed:**
   - Acknowledge existing recommendation first
   - Create new investigation with explicit trigger_ref

3. **If client is retrying aggressively:**
   - Implement exponential backoff on client side
   - Add idempotency key to prevent duplicate requests

**Prevention:**
- Clients should check for existing investigations before creating new ones
- Implement idempotency keys (using `trigger_ref` constraint)
- Monitor 409 rate (should be < 5% of total requests)

---

### 7. Auth0/JWKS Validation Failures

**Symptoms:**
- `GET /api/v1/ops-agent/*` returns 401
- Error: "Invalid token", "Unable to verify token"
- Logs: "JWKS fetch failed", "Token validation failed"

**Diagnosis:**
```bash
# Check Auth0 configuration
doppler secrets get AUTH0_DOMAIN
doppler secrets get AUTH0_AUDIENCE

# Test JWKS endpoint
curl https://$AUTH0_DOMAIN/.well-known/jwks.json

# Verify token in debugger
# https://jwt.io/ or https://auth0.com/docs/quickstart/backend/python/01-authorization
```

**Resolution Actions:**

1. **If JWKS fetch is failing:**
   ```bash
   # Check network connectivity to Auth0
   curl -v https://$AUTH0_DOMAIN/.well-known/jwks.json

   # Update JWKS cache TTL if needed (default 3600s)
   doppler secrets set AUTH0_JWKS_CACHE_TTL=1800
   kubectl rollout restart deployment/ops-agent
   ```

2. **If token is invalid:**
   - Verify token includes required scopes
   - Check token expiration (`exp` claim)
   - Verify `aud` matches `AUTH0_AUDIENCE`

3. **If Auth0 tenant is down:**
   - Check Auth0 status page: https://status.auth0.com/
   - Escalate to security team

**Prevention:**
- Set up alerts for 401 rate > 5% for 5 minutes
- Monitor JWKS fetch failures
- Use cached JWKS with appropriate TTL
- Test token validation in smoke tests

---

### 8. Feature Flag Rollback Procedures

**Symptoms:**
- New feature causing issues
- Need to quickly disable a feature
- Gradual rollout showing problems

**Diagnosis:**
```bash
# List current feature flags
doppler secrets list | grep OPS_AGENT_ENABLE
doppler secrets list | grep VECTOR_

# Check which features are active in logs
grep "feature_flag" /var/log/ops-agent/app.log | tail -20
```

**Resolution Actions:**

These are emergency rollback controls, not steady-state defaults. Restore defaults after incident resolution.

1. **Disable LLM reasoning:**
   ```bash
   doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=false
   kubectl rollout restart deployment/ops-agent
   ```

2. **Disable vector similarity search:**
   ```bash
   doppler secrets set VECTOR_ENABLED=false
   kubectl rollout restart deployment/ops-agent
   ```

   If you keep vector enabled, run provider preflight immediately after restart:
   ```bash
   doppler run -- uv run python -c "import asyncio; from app.clients.embedding_client import EmbeddingClient; r=asyncio.run(EmbeddingClient().embed('runbook preflight')); print(len(r.embedding), r.model)"
   ```
   Expected: non-empty embedding vector with configured `VECTOR_DIMENSION`.

3. **Disable conflict matrix:**
   ```bash
   doppler secrets set OPS_AGENT_CONFLICT_MATRIX_ENABLED=false
   kubectl rollout restart deployment/ops-agent
   ```

4. **Disable explanation builder:**
   ```bash
   doppler secrets set OPS_AGENT_EXPLANATION_BUILDER_ENABLED=false
   kubectl rollout restart deployment/ops-agent
   ```

5. **Disable rule draft export:**
   ```bash
   doppler secrets set OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT=false
   kubectl rollout restart deployment/ops-agent
   ```

**Prevention:**
- Always roll out features gradually (canary deployment)
- Monitor metrics closely after each rollout
- Have clear rollback criteria defined
- Test rollback procedures during drills

---

## Monitoring and Alerting

### Key Metrics to Watch

1. **Investigation Latency**
   - `ops_agent_investigation_latency_seconds` P95 < 500ms (fallback path target)
   - `ops_agent_investigation_latency_seconds{mode="llm"}` P95 < 90s
   - Alert if P95 > 2× baseline for 15 minutes

2. **Error Rates**
   - `ops_agent_dependency_failures_total{dependency_type="database"}` < 1%
   - `ops_agent_dependency_failures_total{dependency_type="llm"}` < 5%
   - Alert if error ratio > 2% for 10 minutes

3. **Connection Pool**
   - Database pool utilization < 80%
   - Alert if > 80% for 5 minutes

4. **Queue Depth**
   - `ops_agent_recommendation_queue_open` should be < 1000
   - Alert if > 5000 for 10 minutes

5. **Investigation Rate**
   - `ops_agent_investigation_requests_total` should be > 0 (normal operation)
   - Alert if = 0 for 15 minutes (service may be down)

### Recommended Alerting Thresholds

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| Investigation P95 latency | 2× baseline | 5× baseline | 15 min |
| 5xx error ratio | 2% | 5% | 10 min |
| 4xx error ratio | 5% | 10% | 15 min |
| Connection pool utilization | 80% | 95% | 5 min |
| LLM failure ratio | 10% | 25% | 15 min |
| Recommendation queue depth | 1000 | 5000 | 10 min |

---

## Common Commands

### Check Service Health
```bash
# Health endpoint
curl http://localhost:8003/api/v1/health

# Pod status (Kubernetes)
kubectl get pods -l app=ops-agent

# Service logs
kubectl logs -l app=ops-agent --tail=100 -f
```

### View Traces
```bash
# Open Jaeger UI
open http://localhost:16686

# Filter by operation name
# Look for: "POST /api/v1/ops-agent/investigations/run"
```

### Toggle Feature Flags
```bash
# List current flags
doppler secrets list | grep OPS_AGENT_ENABLE

# Disable LLM reasoning
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=false
doppler run -- kubectl rollout restart deployment/ops-agent
```

### Database Queries
```sql
-- Check recent investigations
SELECT run_id, status, created_at, mode
FROM fraud_gov.ops_agent_runs
ORDER BY created_at DESC
LIMIT 10;

-- Check open recommendations
SELECT COUNT(*), priority
FROM fraud_gov.ops_agent_recommendations
WHERE status = 'OPEN'
GROUP BY priority;

-- Check for errors in last hour
SELECT COUNT(*), error_type
FROM fraud_gov.ops_agent_audit_log
WHERE created_at > NOW() - INTERVAL '1 hour'
  AND event_type = 'error'
GROUP BY error_type;
```

---

## Escalation Paths

1. **SEV1 (Critical)**: Page platform on-call immediately
2. **SEV2 (Major)**: Create incident, notify platform team in Slack
3. **SEV3 (Minor)**: Create ticket, address in next business hours

**Team Contacts:**
- Platform on-call: #platform-on-call
- DBA team: #dba-help
- Security team: #security-on-call

**Related Documentation:**
- [Incidents and Rollback](./incidents-and-rollback.md)
- [Observability](./observability.md)
- [Performance Baselines](./performance-baselines.md)
