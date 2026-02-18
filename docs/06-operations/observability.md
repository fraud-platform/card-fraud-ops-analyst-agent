# Observability

Complete guide to monitoring, logging, tracing, and debugging the Card Fraud Ops Analyst Agent.

## Architecture Note

The Ops Analyst Agent is part of the **card-fraud-platform**. All observability infrastructure (Jaeger, Prometheus, Grafana) runs as part of the platform, not as standalone services.

## Quick Reference: Web UI Access

| Purpose | URL | What You'll See |
|---------|-----|-----------------|
| **Traces** | http://localhost:16686 | Jaeger UI - Request traces, pipeline stages, latencies |
| **Metrics** | http://localhost:9090 | Prometheus UI - Query metrics, view targets |
| **Dashboards** | http://localhost:3000 | Grafana UI - Pre-built dashboards (admin/admin) |
| **Metrics Endpoint** | http://localhost:8003/api/v1/metrics | Raw Prometheus metrics from Ops Agent (requires `X-Metrics-Token`) |
| **Health** | http://localhost:8003/api/v1/health | Service health status |
| **API Docs** | http://localhost:8003/docs | Interactive Swagger documentation |

## Starting the Observability Stack

All observability services are managed from `card-fraud-platform`:

```bash
# From card-fraud-platform directory
cd ../card-fraud-platform

# Start infrastructure (includes Jaeger, Prometheus, Grafana)
docker compose up -d

# Or start specific services
docker compose up -d jaeger prometheus grafana

# Check status
docker compose ps
```

---

## Telemetry Pillars

### 1. Structured Logging

**Format:** JSON (production) or Console (local)

**Log Levels:**
- `DEBUG` - Detailed diagnostic information
- `INFO` - Normal operation milestones
- `WARNING` - Unexpected but recoverable conditions
- `ERROR` - Error conditions that don't terminate the request
- `CRITICAL` - Severe errors that may cause service failure

**Viewing Logs:**

```bash
# Local development - console output
doppler run -- uv run python scripts/run_dev.py

# With Docker - follow logs
docker logs -f ops-agent

# Filter by request ID (for distributed tracing)
docker logs ops-agent | grep "request_id:abc-123"

# Filter errors only
docker logs ops-agent | grep '"level":"ERROR"'
```

**Log Fields (Structured JSON):**
```json
{
  "event": "Investigation completed",
  "level": "info",
  "logger": "app.agents.pipeline",
  "request_id": "abc-123-def-456",
  "run_id": "0192abcd-1234-5678-9012-abcdef123456",
  "transaction_id": "0192fedc-9876-5432-1098-zyxwvutsrqpon",
  "severity": "HIGH",
  "duration_ms": 1234.5,
  "timestamp": "2026-02-17T10:30:45.123Z"
}
```

---

### 2. Metrics (Prometheus)

**Endpoint:** `http://localhost:8003/api/v1/metrics`

Access control: `/api/v1/metrics` requires `X-Metrics-Token` and validates against `METRICS_TOKEN` using constant-time comparison.

**Key Metrics to Monitor:**

| Metric Name | Type | Labels | Purpose |
|-------------|------|--------|---------|
| `ops_agent_investigation_requests_total` | Counter | `mode`, `status` | Total investigation requests |
| `ops_agent_investigation_latency_seconds` | Histogram | `mode` | End-to-end latency |
| `ops_agent_pipeline_stage_latency_seconds` | Histogram | `stage` | Per-stage latency |
| `ops_agent_recommendations_generated_total` | Counter | `type`, `severity` | Recommendations created |
| `ops_agent_llm_calls_total` | Counter | `status` | LLM API calls |
| `ops_agent_llm_latency_seconds` | Histogram | - | LLM response time |
| `ops_agent_llm_tokens_total` | Counter | `type` | Token consumption |
| `ops_agent_dependency_failures_total` | Counter | `dependency` | External service failures |

**Query Examples (PromQL):**

```promql
# Investigation success rate (last 5m)
rate(ops_agent_investigation_requests_total{status="success"}[5m]) /
rate(ops_agent_investigation_requests_total[5m])

# P95 investigation latency
histogram_quantile(0.95,
  rate(ops_agent_investigation_latency_seconds_bucket[5m])
)

# LLM error rate
rate(ops_agent_llm_calls_total{status="error"}[5m]) /
rate(ops_agent_llm_calls_total[5m])
```

---

### 3. Distributed Tracing (Jaeger)

**UI:** http://localhost:16686

**Why Jaeger Shows Empty:**

If you see no traces in Jaeger, check:

1. **OTEL_ENDPOINT is configured:**
   ```bash
   doppler secrets get OTEL_OTLP_ENDPOINT
   # Should be: http://localhost:4317  (gRPC) or http://localhost:4318 (HTTP)
   ```

2. **Jaeger is running:**
   ```bash
   docker ps | grep jaeger
   # Should see: jaeger:latest ... :16686->16686/tcp
   ```

3. **Start the infrastructure:**
   ```bash
   # From card-fraud-platform root (if you have sibling project)
   docker compose up -d jaeger prometheus grafana
   ```

**Using Jaeger UI:**

1. Open http://localhost:16686
2. **Service:** Select `card-fraud-ops-analyst-agent`
3. **Operation:** Select `POST /api/v1/ops-agent/investigations/run`
4. **Look for traces** in the last hour
5. **Click on a trace** to see span details

**What You'll See in Traces:**

```
├── POST /api/v1/ops-agent/investigations/run (total duration)
    ├── context_build (fetch transaction data)
    ├── pattern_analysis (fraud pattern detection)
    ├── similarity_analysis (vector search)
    ├── llm_reasoning (LLM call - if enabled)
    │   ├── llm.http_request (actual HTTP call to Ollama)
    │   └── llm.response_parsing
    └── recommendations (generate recommendations)
```

**Trace Attributes (for filtering):**
- `run.id` - Investigation run ID
- `run.mode` - `deterministic` or `hybrid`
- `transaction.id` - Transaction being investigated
- `pattern.severity` - `CRITICAL`, `HIGH`, `MEDIUM`, `LOW`
- `llm.latency_ms` - LLM response time in milliseconds
- `llm.model` - Model used (e.g., `ollama/gpt-oss:20b`)

---

### 4. Request ID Propagation

**Purpose:** Correlate requests across microservices.

**How It Works:**

1. **Incoming request** to Ops Agent includes `X-Request-ID` header
2. Ops Agent **stores** it in contextvar
3. **Outbound calls** to Rule Management, Ollama, Embedding service include same `X-Request-ID`
4. All logs across services share the same `request_id`

**Request Flow Example:**

```
Portal (X-Request-ID: abc-123)
  ↓
Ops Agent (X-Request-ID: abc-123)
  ├── logs: {"request_id": "abc-123", ...}
  ├── → Rule Management (X-Request-ID: abc-123)
  ├── → Ollama LLM (X-Request-ID: abc-123)
  └── → Ollama Embeddings (X-Request-ID: abc-123)
```

**Checking Request ID Propagation:**

```bash
# Check logs for specific request ID
docker logs ops-agent | grep "request_id:abc-123"
docker logs rule-management | grep "request_id:abc-123"

# Response headers always include X-Request-ID
curl -v http://localhost:8003/api/v1/health
# Look for: < X-Request-ID: <uuid>
```

---

## Validation Checklist (Logs + Metrics + Traces)

Use this end-to-end check when onboarding or validating a new environment:

```bash
# 1) Ensure shared observability infra is up (run from card-fraud-platform)
docker compose up -d jaeger prometheus grafana
docker compose ps

# 2) Health check with explicit request ID
curl -i -H "X-Request-ID: obs-check-001" http://localhost:8003/api/v1/health
# Expect HTTP 200 and response header X-Request-ID: obs-check-001

# 3) Trigger one investigation run (local auth bypass may be enabled)
curl -s -X POST http://localhost:8003/api/v1/ops-agent/investigations/run \
  -H "Content-Type: application/json" \
  -H "X-Request-ID: obs-check-002" \
  -d '{"transaction_id":"00000000-0000-7000-8000-000000000001","mode":"quick"}'

# 4) Verify metrics are exposed and include ops-agent counters
curl -s -H "Accept: text/plain" -H "X-Metrics-Token: $METRICS_TOKEN" http://localhost:8003/api/v1/metrics | grep ops_agent_investigation_requests_total

# 5) Verify logs include request_id/run context
docker logs ops-agent --tail 200 | grep -E "obs-check-00|run_id"
```

Jaeger validation:
1. Open http://localhost:16686
2. Select service `card-fraud-ops-analyst-agent`
3. Search recent traces for operation `POST /api/v1/ops-agent/investigations/run`
4. Confirm stage spans exist (`context_build`, `pattern_analysis`, `similarity_analysis`, `llm_reasoning`, `recommendations`)
5. Confirm span attributes include `run.id` and `transaction.id`

---

## Debugging Guide

### Problem: Investigation is slow

**Step 1: Check Jaeger trace**
```bash
# Open http://localhost:16686
# Find your trace, look for slow spans
```

**Step 2: Check per-stage metrics**
```bash
curl -H "X-Metrics-Token: $METRICS_TOKEN" http://localhost:8003/api/v1/metrics | grep pipeline_stage_latency
```

**Step 3: Check logs for errors**
```bash
docker logs ops-agent | grep ERROR
```

**Step 4: Identify the bottleneck**
- `context_build` > 100ms → Check TM API response time
- `similarity_analysis` > 200ms → Check vector search query
- `llm_reasoning` > 30s → LLM provider slow, consider fallback

---

### Problem: No traces in Jaeger

**Diagnosis:**

```bash
# 1. Check Jaeger is running
docker ps | grep jaeger

# 2. Check OTLP endpoint config
doppler secrets get OTEL_OTLP_ENDPOINT

# 3. Check service is sending traces
# Look for logs about telemetry setup
docker logs ops-agent | grep -i "telemetry\|otel"

# 4. Test connectivity to Jaeger
curl -v http://localhost:4317  # gRPC port
curl -v http://localhost:4318  # HTTP port
```

**Fix:**

```bash
# Set OTLP endpoint to Jaeger collector
doppler secrets set OTEL_OTLP_ENDPOINT=http://localhost:4317

# Restart the service
kubectl rollout restart deployment/ops-agent
# Or locally: restart your dev server
```

---

### Problem: Can't correlate logs across services

**Diagnosis:**

```bash
# Check if request IDs are being propagated
curl -v -H "X-Request-ID: test-123" http://localhost:8003/api/v1/health
# Look for: < X-Request-ID: test-123

# Check downstream service logs for same ID
docker logs rule-management | grep "test-123"
```

**Fix:**

Ensure all services use the same `X-Request-ID` header name (case-insensitive).

---

## Centralized Logging (Recommended for Production)

For production deployments, use a centralized log aggregation stack:

### Option 1: Loki + Grafana (Lightweight)

**docker-compose.yml addition:**
```yaml
services:
  loki:
    image: grafana/loki:latest
    ports:
      - "3100:3100"
    command: -config.file=/etc/loki/local-config.yaml

  promtail:
    image: grafana/promtail:latest
    volumes:
      - /var/log:/var/log:ro
      - ./promtail-config.yml:/etc/promtail/config.yml
```

**View logs in Grafana:**
1. Open http://localhost:3000
2. Explore → Loki
3. Query: `{job="ops-agent"} |= "error"`

### Option 2: ELK Stack (Elasticsearch, Logstash, Kibana)

**docker-compose.yml addition:**
```yaml
services:
  elasticsearch:
    image: docker.elastic.co/elasticsearch/elasticsearch:8.x
    environment:
      - discovery.type=single-node
    ports:
      - "9200:9200"

  kibana:
    image: docker.elastic.co/kibana/kibana:8.x
    ports:
      - "5601:5601"
    depends_on:
      - elasticsearch
```

**View logs in Kibana:**
1. Open http://localhost:5601
2. Stack Management → Index Patterns → Create `logs-*`
3. Discover → Filter by `request_id`

### Option 3: CloudWatch (AWS)

**Add to Doppler/config:**
```bash
OTEL_EXPORTER_OTLP_ENDPOINT=https://otel.aws.{region}.amazonaws.com
AWS_REGION=us-east-1
```

**View logs:**
1. CloudWatch Logs → Log groups → `/aws/ecs/ops-agent`
2. Search logs by `request_id`

---

## Alerting Recommendations

| Alert | Condition | Duration | Severity |
|-------|-----------|----------|----------|
| High error rate | `error_rate > 5%` | 5 min | WARNING |
| Investigation latency P95 | `p95_latency > 5s` | 10 min | WARNING |
| LLM failures | `llm_error_rate > 10%` | 5 min | WARNING |
| No requests | `request_count = 0` | 15 min | CRITICAL |
| Database pool exhaustion | `pool_utilization > 90%` | 2 min | CRITICAL |

**Prometheus Alert Rules:**

```yaml
groups:
  - name: ops_agent_alerts
    rules:
      - alert: OpsAgentHighErrorRate
        expr: |
          rate(ops_agent_investigation_requests_total{status="error"}[5m])
          / rate(ops_agent_investigation_requests_total[5m]) > 0.05
        for: 5m
        annotations:
          summary: "High error rate in Ops Agent"
```

---

## Troubleshooting Checklist

- [ ] Check service health: `curl http://localhost:8003/api/v1/health`
- [ ] Check logs for errors: `docker logs ops-agent | grep ERROR`
- [ ] Check metrics endpoint: `curl -H "X-Metrics-Token: $METRICS_TOKEN" http://localhost:8003/api/v1/metrics`
- [ ] Check Jaeger for traces: http://localhost:16686
- [ ] Verify OTLP endpoint: `doppler secrets get OTEL_OTLP_ENDPOINT`
- [ ] Check feature flags: `doppler secrets | grep OPS_AGENT_ENABLE`
- [ ] Check database connectivity: `psql $DATABASE_URL_APP -c "SELECT 1"`
- [ ] Check LLM provider: `curl $LLM_BASE_URL/v1/models`

---

## Related Documentation

- [Runbooks](./runbooks.md) - Operational procedures
- [Incidents and Rollback](./incidents-and-rollback.md) - Incident response
- [Performance Baselines](./performance-baselines.md) - Expected performance metrics
