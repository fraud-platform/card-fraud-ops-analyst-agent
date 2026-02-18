# OpenAPI Outline (v1)

## Base

- Title: `Card Fraud Ops Analyst Agent API`
- Base path: `/api/v1/ops-agent`
- Content type: `application/json`

## Tags

- `investigations`
- `insights`
- `recommendations`
- `rule-drafts`
- `health`

## Security

OAuth2 JWT bearer with Auth0 audience and scope checks.

## Endpoint Summary

- `POST /investigations/run`
- `GET /investigations/{run_id}`
- `GET /transactions/{transaction_id}/insights`
- `GET /worklist/recommendations`
- `POST /recommendations/{recommendation_id}/acknowledge`
- `POST /rule-drafts`
- `POST /rule-drafts/{rule_draft_id}/export`

## Shared Components

- `InvestigationRunRequest`
- `InvestigationRunResponse`
- `InsightSnapshot`
- `RecommendationItem`
- `RuleDraftPackage`
- `ApiError`

## Error Envelope

```json
{
  "error": "string",
  "code": "string",
  "details": {}
}
```

## Versioning Policy

- v1 is additive-only.
- Breaking changes require v2 path and migration notes.
