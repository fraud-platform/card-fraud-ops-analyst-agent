# Portal Integration

Portal UI integration with `card-fraud-intelligence-portal` is complete and functional.

## UI Modules

### 1. Transaction Insight Panel

Displays the latest severity score, insight summary, and evidence snippets for a selected transaction. Links to the full investigation run.

### 2. Recommendation Queue

Lists pending analyst recommendations. Supports filtering by status, severity, and type. Supports acknowledge and reject actions.

### 3. Rule Draft Action

Allows an analyst to generate and preview a draft rule package from an investigation. Requires explicit analyst confirmation before export to Rule Management.

## UX Constraints

- Recommendations are advisory. They do not trigger automatic rule changes.
- Show evidence provenance and the generated timestamp on every recommendation.
- Keep the human decision boundary clearly visible in the UI.
- Show action history per recommendation.

## API Integration Map

All endpoints use the base prefix `/api/v1/ops-agent`. Auth0 Bearer token required for all calls.

| UI Action | Method | Full Path |
|-----------|--------|-----------|
| Transaction detail page | `GET` | `/api/v1/ops-agent/transactions/{transaction_id}/insights` |
| Trigger deep investigation | `POST` | `/api/v1/ops-agent/investigations/run` |
| Fetch investigation result | `GET` | `/api/v1/ops-agent/investigations/{run_id}` |
| Recommendation queue page | `GET` | `/api/v1/ops-agent/worklist/recommendations` |
| Acknowledge recommendation | `POST` | `/api/v1/ops-agent/worklist/recommendations/{id}/acknowledge` |
| Create rule draft | `POST` | `/api/v1/ops-agent/rule-drafts` |
| Export rule draft | `POST` | `/api/v1/ops-agent/rule-drafts/{id}/export` |

## Frontend Permission Mapping

| Action | Required Scope |
|--------|----------------|
| View insight panel, recommendation queue, investigation results | `ops_agent:read` |
| Trigger investigation run | `ops_agent:run` |
| Acknowledge or reject recommendations | `ops_agent:ack` |
| Create or export rule drafts | `ops_agent:draft` |
| Admin operations | `ops_agent:admin` |

## Authentication

All requests require an Auth0 Bearer token:

```
Authorization: Bearer <access_token>
```

Auth0 audience: `https://fraud-ops-analyst-agent-api`
Auth0 tenant: `dev-gix6qllz7yvs0rl8.us.auth0.com`

## Example Requests

### Get Transaction Insight

```http
GET /api/v1/ops-agent/transactions/3fa85f64-5717-4562-b3fc-2c963f66afa6/insights
Authorization: Bearer <token>
```

### Run Investigation

```http
POST /api/v1/ops-agent/investigations/run
Authorization: Bearer <token>
Content-Type: application/json

{
  "transaction_id": "3fa85f64-5717-4562-b3fc-2c963f66afa6",
  "mode": "deterministic"
}
```

### Acknowledge Recommendation

```http
POST /api/v1/ops-agent/worklist/recommendations/3fa85f64-5717-4562-b3fc-2c963f66afa6/acknowledge
Authorization: Bearer <token>
Content-Type: application/json

{
  "analyst_note": "Reviewed and confirmed."
}
```
