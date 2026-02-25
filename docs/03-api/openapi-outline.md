# OpenAPI Outline (v1)

## Base

- Title: `Card Fraud Ops Analyst Agent API`
- Base path: `/api/v1/ops-agent`
- Content type: `application/json`

## Tags

- `investigations`
- `insights`
- `recommendations`
- `monitoring`
- `health`

## Security

OAuth2 JWT bearer with Auth0 audience and scope checks.

## Endpoint Summary

- `POST /investigations/run`
- `GET /investigations`
- `GET /investigations/{investigation_id}`
- `POST /investigations/{investigation_id}/resume`
- `GET /investigations/{investigation_id}/rule-draft`
- `GET /transactions/{transaction_id}/insights`
- `GET /worklist/recommendations`
- `POST /worklist/recommendations/{recommendation_id}/acknowledge`
- `GET /api/v1/metrics` (requires `X-Metrics-Token`)

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
