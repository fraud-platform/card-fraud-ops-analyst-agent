# Operational Runbooks

This document provides step-by-step procedures for common operational scenarios. Each scenario includes symptoms, diagnosis steps, resolution actions, and prevention strategies.

## Quick Reference

| Scenario | Severity | First Action | Escalation |
|----------|----------|--------------|------------|
| Investigation runtime failure | SEV2 | Check feature flags and dependency health | Platform team |
| Database connection exhaustion | SEV2 | Check pool metrics, restart workers if needed | DBA team |
| LLM service degradation | SEV3 | Validate provider URL + model availability | LLM provider |
| High latency investigations | SEV3 | Review traces, check vector search | N/A |
| Auth0/JWKS validation failures | SEV2 | Verify JWKS URL, check token issuer | Security team |
| Investigation not found (404) | SEV3 | Check timing, verify DB state | N/A |
| Duplicate investigation (409) | SEV3 | Review trigger_ref, check for race condition | N/A |

## Container Context (Platform Group)

In local/shared platform environments, Ops Agent runs as the `ops-analyst-agent` service in
`card-fraud-platform` using `docker-compose.yml` + `docker-compose.apps.yml` with `--profile platform`.

```bash
# From card-fraud-platform
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile platform ps ops-analyst-agent transaction-management
docker compose -f docker-compose.yml -f docker-compose.apps.yml --profile platform logs -f ops-analyst-agent
```

Use these commands when reproducing operational issues locally. Kubernetes commands in this runbook
apply to cluster deployments only.

Default platform posture:
- Keep `OPS_AGENT_ENABLE_LLM_REASONING=true` and `VECTOR_ENABLED=true` in normal operation.
- Use feature-flag disablement only as a time-bound incident mitigation with explicit on-call approval.

## Common Operational Scenarios

### 1. Investigation Runtime Failure

**Symptoms:**
- `POST /api/v1/ops-agent/investigations/run` returns 500 or 503
- Error logs showing `OpsAgentError` variants
- Metrics spike in `ops_agent_dependency_failures_total{dependency=...}`

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
   Validate endpoint and model first; do not treat degraded LLM output as a pass condition.
   ```bash
   doppler secrets get LLM_PROVIDER
   doppler secrets get LLM_BASE_URL
   doppler secrets get LLM_API_KEY

   # Verify provider advertises required model
   printf "Authorization: Bearer %s\n" "$LLM_API_KEY" > /tmp/ops_agent_llm_header
   curl -H @/tmp/ops_agent_llm_header "$LLM_BASE_URL/api/tags"
   rm -f /tmp/ops_agent_llm_header
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
- Monitor `ops_agent_dependency_failures_total` by dependency
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
   doppler run --project card-fraud-platform --config local -- \
     docker compose -f docker-compose.yml -f docker-compose.apps.yml \
     --profile platform up -d --build transaction-management ops-analyst-agent
   ```

   Important:
   - Do not add pool settings into `DATABASE_URL_*` query strings.
   - Set pool values via `DATABASE_POOL_SIZE` and `DATABASE_MAX_OVERFLOW` environment variables.

2. **Root cause analysis:**
   - Check for long-running queries in traces
   - Verify connection recycling is working (1800s default)
   - Review worker count (4 workers x 20 connections = 80 max)

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
- Metrics: `ops_agent_dependency_failures_total{dependency="llm"}`

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

1. **Validate OpenAI endpoint connectivity:**
   ```bash
   curl -H "Authorization: Bearer $LLM_API_KEY" "$LLM_BASE_URL/models"
   ```

2. **Validate model availability for this run:**
   ```bash
   curl -s -H "Authorization: Bearer $LLM_API_KEY" "$LLM_BASE_URL/models" \
     | jq -r '.data[].id'
   ```
   Confirm the selected `LLM_PROVIDER` model is returned.

3. **If authentication fails:**
   - Verify `LLM_API_KEY` is set and valid in Doppler
   - Verify `LLM_PROVIDER` uses `provider/model` format (e.g. `openai/gpt-5-mini`)
   - Verify `LLM_BASE_URL` is `https://api.openai.com/v1`

**Prevention:**
- Monitor `ops_agent_investigation_latency_seconds{mode="llm"}`
- Set up alert for P95 > 60s for 15 minutes
- Fail the matrix run if provider/model preflight fails.

### 3a. E2E Matrix Run Guardrails

Use these checks every time before running `run_e2e_matrix_detailed.py` or pytest E2E matrix workflows.

**Preflight Checklist:**

1. Recreate infra with tracked compose files only:
  ```bash
  doppler run --project card-fraud-platform --config local -- \
    docker compose -f C:/Users/kanna/github/card-fraud-platform/docker-compose.yml \
    -f C:/Users/kanna/github/card-fraud-platform/docker-compose.apps.yml \
    --profile platform up -d --build transaction-management ops-analyst-agent
  ```

2. Confirm both services are healthy (no stale container path):
  ```bash
  curl http://localhost:8003/api/v1/health/ready
  curl http://localhost:8002/api/v1/health
  ```

3. Confirm selected model is present on the runtime provider endpoint:
  ```powershell
  $envText = docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' card-fraud-ops-analyst-agent
  $llm_api_key = ($envText | Select-String '^LLM_API_KEY=').ToString().Split('=', 2)[1].Trim()
  if (-not $llm_api_key) {
    Write-Error "LLM_API_KEY missing from container env."
    exit 1
  }
  $llm_provider = ($envText | Select-String '^LLM_PROVIDER=').ToString().Split('=', 2)[1].Trim()
  $llm_base_url = ($envText | Select-String '^LLM_BASE_URL=').ToString().Split('=', 2)[1].Trim()

  if (-not $llm_provider -or -not $llm_base_url) {
    Write-Error "LLM_PROVIDER or LLM_BASE_URL is missing from container env."
    exit 1
  }

  $model = ($llm_provider -split '/', 2)[1].Trim()
  $modelsResponse = Invoke-RestMethod -Headers @{ Authorization = "Bearer $llm_api_key" } -Uri "$llm_base_url/models"
  $modelIds = $modelsResponse.data | Select-Object -ExpandProperty id
  if ($modelIds -notcontains $model) {
    Write-Warning "Model '$model' not in /models list — attempting chat call anyway."
  } else {
    Write-Output "LLM preflight OK: $model found in /models."
  }
  ```

4. Validate container model configuration matches test request:
  ```bash
  docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' card-fraud-ops-analyst-agent \
    | Select-String '^LLM_PROVIDER=\|^PLANNER_MODEL_NAME='
  ```

5. Ensure run output is KPI-clean before sharing:
   - `kpi_all_pass=True`
   - `reasoning_llm_failed:* = 0`
   - `reasoning_llm_failed` absent from all scenario rows
   - `tool_failure:* = 0`
   - `status_counts["COMPLETED"] == scenario_count`

### 3b. No Silent Failures

- A scenario must include both:
  - `issues` list in matrix output JSON (`e2e-31matrix-report-...json`)
  - `Fraud Analyst Assessment` stage status in HTML
- If both are empty/green while actual tool failures are observed in service logs, treat the run as invalid and stop.
- Do not report pass/fail from partial report snippets; always use the run summary (`status_counts`, `issue_counts`, `kpi_*`) to decide publishability.

### 3d. LLM Preflight (Mandatory)

- Quick command check for model/key health before running suites:
  ```powershell
  $envText = docker inspect -f '{{range .Config.Env}}{{println .}}{{end}}' card-fraud-ops-analyst-agent
  $llm_provider = ($envText | Select-String '^LLM_PROVIDER=').ToString().Split('=', 2)[1].Trim()
  $llm_base_url = ($envText | Select-String '^LLM_BASE_URL=').ToString().Split('=', 2)[1].Trim()
  $llm_api_key = ($envText | Select-String '^LLM_API_KEY=').ToString().Split('=', 2)[1].Trim()
  $model = ($llm_provider -split '/', 2)[1].Trim()

  Invoke-RestMethod -Headers @{ Authorization = "Bearer $llm_api_key" } -Uri "$llm_base_url/models" |
    Select-Object -ExpandProperty data | Select-Object -ExpandProperty id | Select-String -Pattern "^$([regex]::Escape($model))$"

  $body = @{model=$model; messages=@(@{role='user'; content='health check'}); max_completion_tokens=50} | ConvertTo-Json -Depth 4
  Invoke-RestMethod -Method Post -Uri "$llm_base_url/chat/completions" `
    -Headers @{ Authorization = "Bearer $llm_api_key"; 'Content-Type'='application/json' } `
    -Body $body
  ```
- Fail immediately if:
  - `/api/tags` is not HTTP 200
  - model is not present in tags response
  - `/api/chat` does not return HTTP 200
  - chat response body includes usage/quota errors
- Equivalent code-level preflight:
  `doppler run --config local -- uv run pytest tests/e2e/test_scenarios.py::test_llm_chat_preflight -v`

### 3e. No-Mistake Run Gate

Run this order as a hard gate before any matrix/e2e execution in the same shell:

1. Recreate infra with tracked compose files only.
2. Validate both services are healthy (`/api/v1/health/ready`, `8002` and `8003` containers).
3. Run both LLM checks:
   - `/api/tags` includes selected model
   - `/api/chat` returns HTTP 200
4. Confirm model tokens match between compose env and provider session.
5. Confirm container image/source timestamp alignment (`scripts/docker_guard.py` checks).
6. Capture run summary and stop immediately if:
   - `kpi_all_pass != True`
   - `reasoning_llm_failed` exists
   - `tool_failure` > 0
   - `status_counts["FAILED"] > 0`

If any gate step fails, stop and do not publish any report as a demo artifact.

### 3c. Common Recovery

- If preflight model check fails: update compose/env for a supported model name and restart both services before rerunning.
- If stale container check fails: rerun `docker compose ... --build` with the same profile.
- If LLM timeouts continue after valid model/preflight: switch to a known stable smaller model and retune timeout for the run only.
- If LLM API returns usage/quota errors (for example `reached your weekly usage limit`): rotate `LLM_API_KEY` (or use a different provider/model) and rerun preflight before retrying matrix/e2e.

**Failure handling:**

1. **If preflight model tag is missing**: stop and switch to a valid model name for this session.
2. **If `run_e2e_matrix_detailed.py` returns non-zero**: do not publish report artifacts as demo evidence until rerun clears KPI gate.
3. **If `reasoning_tool` starts timing out**: treat as infrastructure/provider issue (not a graph fallback signal), increase model timeout or switch model only after validating provider availability and cost/sla impact.
4. **If `reasoning_llm_failed:not_executed` appears in matrix output**: stop the run, run API key/token checks and `/api/chat` smoke test with current model before retrying.

---

### 5. High Latency Investigations

**Symptoms:**
- `POST /investigations/run` taking > 90s (LLM) in fail-fast mode
- Analyst complaints about slow investigations
- Metrics: `ops_agent_investigation_latency_seconds` P95 above baseline

**Diagnosis:**
```bash
# View recent traces in Jaeger
# http://localhost:16686
# Look for slow spans in investigation graph

# Check which tool is slow
grep "Tool executed successfully" /var/log/ops-agent/app.log | tail -50

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
   - Fail the release gate until resolved for LLM mode

4. **If recommendation generation is slow (> 100ms):**
   - Check conflict matrix computation (if enabled)
   - Verify explanation builder is not hitting rate limits

**Prevention:**
- Monitor each tool execution latency separately
- Set up alerts for each tool exceeding baseline
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
   - `ops_agent_investigation_latency_seconds` P95 < 90s (agentic LLM mode gate)
   - `ops_agent_investigation_latency_seconds{mode="llm"}` P95 < 90s
   - Alert if P95 > 2x baseline for 15 minutes

2. **Error Rates**
   - `ops_agent_dependency_failures_total{dependency="database"}` < 1%
   - `ops_agent_dependency_failures_total{dependency="llm"}` < 5%
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
| Investigation P95 latency | 2x baseline | 5x baseline | 15 min |
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
