# Ops Agent API Contract v1

## Contract Status

`v1 - Draft for freeze`

## Security

| Endpoint | Required Scope |
|---|---|
| `POST /investigations/run` | `ops_agent:run` |
| `GET /investigations/{run_id}` | `ops_agent:read` |
| `GET /transactions/{transaction_id}/insights` | `ops_agent:read` |
| `GET /worklist/recommendations` | `ops_agent:read` |
| `POST /recommendations/{recommendation_id}/acknowledge` | `ops_agent:ack` |
| `POST /rule-drafts` | `ops_agent:draft` |
| `POST /rule-drafts/{rule_draft_id}/export` | `ops_agent:draft` |

## 1. Run Investigation

### Request

`POST /api/v1/ops-agent/investigations/run`

```json
{
  "mode": "quick",
  "transaction_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "case_id": null,
  "include_rule_draft_preview": false
}
```

### Response

```json
{
  "run_id": "90c7a34f-52c1-4890-b495-4f6f21435f01",
  "status": "SUCCESS",
  "mode": "quick",
  "transaction_id": "0f8fad5b-d9cb-469f-a165-70867728950e",
  "insight": {
    "insight_id": "0d132e6b-47d3-48de-92d1-6d13a8877fb8",
    "severity": "HIGH",
    "summary": "Unusual cross-merchant burst with elevated decline ratio",
    "generated_at": "2026-02-13T12:00:00Z"
  },
  "recommendations": [
    {
      "recommendation_id": "f2ce7b21-dff8-4f84-b638-c58d1f6a0878",
      "type": "rule_candidate",
      "status": "OPEN",
      "priority": 1,
      "payload": {
        "title": "Consider velocity threshold refinement for merchant cluster",
        "impact": "Expected to reduce repeat false negatives"
      }
    }
  ]
}
```

## 2. Get Investigation

`GET /api/v1/ops-agent/investigations/{run_id}`

- Returns full persisted run details including evidence blocks.

## 3. Get Latest Transaction Insights

`GET /api/v1/ops-agent/transactions/{transaction_id}/insights`

- Returns latest insight snapshots for transaction-centric portal panels.

## 4. Recommendation Worklist

`GET /api/v1/ops-agent/worklist/recommendations?status=OPEN&limit=50&cursor=...`

- Keyset pagination.
- Supports filters by severity, type, and owner.

## 5. Acknowledge Recommendation

`POST /api/v1/ops-agent/recommendations/{recommendation_id}/acknowledge`

```json
{
  "action": "ACKNOWLEDGED",
  "comment": "Reviewed and moving to case investigation"
}
```

Allowed `action` values:
- `ACKNOWLEDGED`
- `REJECTED`

## 6. Create Rule Draft

`POST /api/v1/ops-agent/rule-drafts`

```json
{
  "recommendation_id": "f2ce7b21-dff8-4f84-b638-c58d1f6a0878",
  "package_version": "1.0",
  "dry_run": true
}
```

- Generates normalized rule draft package from recommendation evidence.
- Does not activate or approve rules.

## 7. Export Rule Draft

`POST /api/v1/ops-agent/rule-drafts/{rule_draft_id}/export`

```json
{
  "target": "rule-management",
  "target_endpoint": "/api/v1/ops-agent-drafts/import"
}
```

- Exports package for maker-checker flow in Rule Management.

## Error Codes

- `OPS_AGENT_NOT_FOUND`
- `OPS_AGENT_INVALID_REQUEST`
- `OPS_AGENT_SCOPE_FORBIDDEN`
- `OPS_AGENT_CONFLICT`
- `OPS_AGENT_DEPENDENCY_FAILURE`
- `OPS_AGENT_INTERNAL_ERROR`
