# Ops Agent API Contract v1

## Contract Status

`v1 - active`

## Base Path

- Ops-agent routes: `/api/v1/ops-agent`
- Health and metrics routes: `/api/v1`

## Security Scopes

| Endpoint | Required Scope |
|---|---|
| `GET /investigations` | `ops_agent:read` |
| `POST /investigations/run` | `ops_agent:run` |
| `GET /investigations/{investigation_id}` | `ops_agent:read` |
| `GET /investigations/{investigation_id}/trace` | `ops_agent:read` |
| `POST /investigations/{investigation_id}/resume` | `ops_agent:run` |
| `GET /investigations/{investigation_id}/rule-draft` | `ops_agent:read` |
| `GET /transactions/{transaction_id}/insights` | `ops_agent:read` |
| `GET /worklist/recommendations` | `ops_agent:read` |
| `POST /worklist/recommendations/{recommendation_id}/acknowledge` | `ops_agent:ack` |
| `GET /api/v1/metrics` | `X-Metrics-Token` header |

## Endpoints

### 1. List Investigations

`GET /api/v1/ops-agent/investigations?limit=50&offset=0&status=...&transaction_id=...`

- Returns paged investigation summaries.

### 2. Run Investigation

`POST /api/v1/ops-agent/investigations/run`

```json
{
  "mode": "quick",
  "transaction_id": "0f8fad5b-d9cb-469f-a165-70867728950e"
}
```

- Starts an investigation and returns initial state.

### 3. Get Investigation Detail

`GET /api/v1/ops-agent/investigations/{investigation_id}`

- Returns full persisted investigation detail, including insights, recommendations, evidence, and agent trace metadata.

### 4. Resume Investigation

`POST /api/v1/ops-agent/investigations/{investigation_id}/resume`

- Resumes interrupted or failed investigations.

### 5. Get Investigation Rule Draft

`GET /api/v1/ops-agent/investigations/{investigation_id}/rule-draft`

- Returns associated rule draft when available.

### 6. Get Investigation Trace

`GET /api/v1/ops-agent/investigations/{investigation_id}/trace`

- Returns self-contained HTML trace viewer (LangSmith-like experience).
- Displays investigation steps, planner decisions, tool executions, LLM prompts/responses, evidence, and recommendations.
- No external dependencies; all data embedded in HTML.

### 7. Get Transaction Insights

`GET /api/v1/ops-agent/transactions/{transaction_id}/insights`

- Returns insight snapshots and evidence blocks for a transaction.

### 8. Recommendation Worklist

`GET /api/v1/ops-agent/worklist/recommendations?limit=50&cursor=...&severity=...`

- Keyset-style pagination via cursor.

### 9. Acknowledge Recommendation

`POST /api/v1/ops-agent/worklist/recommendations/{recommendation_id}/acknowledge`

```json
{
  "action": "ACKNOWLEDGED",
  "comment": "Reviewed and actioned"
}
```

Allowed `action` values:
- `ACKNOWLEDGED`
- `REJECTED`

## Health and Monitoring

- `GET /api/v1/health`
- `GET /api/v1/health/ready`
- `GET /api/v1/health/live`
- `GET /api/v1/metrics` (requires `X-Metrics-Token`)

## Error Codes

- `OPS_AGENT_NOT_FOUND`
- `OPS_AGENT_INVALID_REQUEST`
- `OPS_AGENT_SCOPE_FORBIDDEN`
- `OPS_AGENT_CONFLICT`
- `OPS_AGENT_DEPENDENCY_FAILURE`
- `OPS_AGENT_INTERNAL_ERROR`
