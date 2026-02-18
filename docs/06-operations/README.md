# 06-operations

Operational controls, governance, observability, and incident procedures.

## Overview

This section contains operational documentation for running the Card Fraud Ops Analyst Agent in production. Key topics include incident response, observability, security governance, and day-to-day operations.

## Key Operational Metrics

The service tracks the following key operational metrics:

- **Investigation Latency**: P95 < 500ms (deterministic), < 90s (LLM)
- **Error Rates**: < 2% (5xx), < 5% (4xx)
- **Connection Pool Utilization**: < 80%
- **Recommendation Queue Depth**: < 1000
- **Investigation Rate**: > 0 per minute (service health)

## Quick Reference

### Check Service Health
```bash
curl http://localhost:8003/api/v1/health
```

### View Recent Traces
```bash
# Open Jaeger UI
open http://localhost:16686
```

### Toggle Feature Flags
```bash
# List current flags
doppler secrets list | grep OPS_AGENT_ENABLE

# Disable LLM reasoning
doppler secrets set OPS_AGENT_ENABLE_LLM_REASONING=false
kubectl rollout restart deployment/ops-agent
```

### Check Database State
```sql
-- Recent investigations
SELECT run_id, status, created_at, mode
FROM fraud_gov.ops_agent_runs
ORDER BY created_at DESC
LIMIT 10;

-- Open recommendations
SELECT COUNT(*), priority
FROM fraud_gov.ops_agent_recommendations
WHERE status = 'OPEN'
GROUP BY priority;
```

## Documentation

- **[Database Operations](./database-operations.md)**: Connection pool tuning, parameterized query security, index maintenance, pool exhaustion response, query optimization patterns, monitoring, and troubleshooting.

- **[Incidents and Rollback](./incidents-and-rollback.md)**: Incident severity levels, response priorities, rollback controls, and post-incident actions.

- **[Observability](./observability.md)**: Telemetry pillars (metrics, logs, traces, audit events), core metrics, log requirements, trace requirements, and alert suggestions.

- **[Runbooks](./runbooks.md)**: Step-by-step procedures for common operational scenarios including pipeline failures, database issues, LLM degradation, high latency, and feature flag rollbacks.

- **[Performance Baselines](./performance-baselines.md)**: Performance targets for pipeline stages, database queries, API endpoints, connection pool metrics, and alerting thresholds.

- **[Model Risk and Prompt Governance](./model-risk-and-prompt-governance.md)**: LLM usage policies, prompt testing procedures, consistency checks, and human-in-the-loop controls.

- **[Security and Data Governance](./security-and-data-governance.md)**: Access controls, audit logging, data retention policies, and compliance requirements.

## Alerting and Escalation

### Alert Thresholds

| Metric | Warning | Critical | Duration |
|--------|---------|----------|----------|
| Investigation P95 latency | 2× baseline | 5× baseline | 15 min |
| 5xx error ratio | 2% | 5% | 10 min |
| Connection pool utilization | 80% | 95% | 5 min |
| LLM failure ratio | 10% | 25% | 15 min |
| Recommendation queue depth | 1000 | 5000 | 10 min |

### Escalation Paths

1. **SEV1 (Critical)**: Page platform on-call immediately
2. **SEV2 (Major)**: Create incident, notify platform team in Slack
3. **SEV3 (Minor)**: Create ticket, address in next business hours

**Team Contacts**:
- Platform on-call: #platform-on-call
- DBA team: #dba-help
- Security team: #security-on-call
