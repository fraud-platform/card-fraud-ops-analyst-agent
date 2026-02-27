# Card Fraud Ops Analyst Agent Documentation

Prometheus scraping endpoint: `/api/v1/metrics` requires `X-Metrics-Token` (`METRICS_TOKEN`).

Documentation-first repository for enterprise-grade ops analyst agent implementation and operations.

## Documentation Standards

- Keep published docs inside `docs/01-setup` through `docs/07-reference`.
- Use lowercase kebab-case file names for topic docs.
- Exceptions: `README.md`, `codemap.md`, and machine-readable schema artifacts.

## Section Index

### `01-setup` - Setup

- `01-setup/local-setup.md`
- `01-setup/doppler-secrets-setup.md`
- `01-setup/database-access-and-roles.md`
- `01-setup/auth0-setup-guide.md`

### `02-development` - Development

- `02-development/developer-guide.md`
- `02-development/architecture.md`
- `02-development/domain-and-data-model.md`
- `02-development/agent-workflow-and-orchestration.md`
- `02-development/agentic-improvement-plan-phase0-2.md`
- `02-development/storage-and-migrations.md`
- `02-development/idempotency-and-replay.md`
- `02-development/performance-patterns.md`

### `03-api` - API

- `03-api/openapi-outline.md`
- `03-api/ops-agent-api-contract-v1.md`
- `03-api/rule-draft-package.schema.v1.json`
- `03-api/insight-event.schema.v1.json`
- `03-api/action-event.schema.v1.json`
- `03-api/portal-integration.md`

### `04-testing` - Testing

- `04-testing/testing-strategy.md`
- `04-testing/acceptance-test-matrix.md`
- `04-testing/non-functional-test-plan.md`

### `05-deployment` - Deployment

- `05-deployment/platform-docker-integration.md`
- `05-deployment/config-and-feature-flags.md`
- `05-deployment/security-configuration.md`
- `05-deployment/release-gates.md`
- `05-deployment/production-readiness-checklist.md`

### `06-operations` - Operations

- `06-operations/database-operations.md`
- `06-operations/runbooks.md`
- `06-operations/observability.md`
- `06-operations/security-and-data-governance.md`
- `06-operations/model-risk-and-prompt-governance.md`
- `06-operations/incidents-and-rollback.md`
- `06-operations/performance-baselines.md`

### `07-reference` - Reference

- `07-reference/overview.md`
- `07-reference/fraud-analyst-workflow.md`
- `07-reference/auth-model.md`
- `07-reference/0000-use-adr.md`
- `07-reference/0001-tm-as-source-of-truth.md`
- `07-reference/0002-human-approval-finality.md`
- `07-reference/0003-fraud-gov-shared-schema-agent-tables.md`
- `07-reference/0005-redaction-and-pseudonym-policy.md`
- `07-reference/0006-rule-draft-package-and-maker-checker-handoff.md`
- `07-reference/0008-rollout-gating-and-slo-policy.md`
- `07-reference/agentic/README.md`
- `07-reference/agentic/adr_001_agentic_fraud_analyst_architecture.md`
- `07-reference/agentic/adr_009_transaction_management_integration_specification.md`

### Archive Policy

- Legacy planning/scratch docs were removed from `docs/archive/`.
- Keep only current, code-aligned agentic documentation under `docs/01-setup` to `docs/07-reference`.

## Core Index Files

- `docs/README.md`
- `docs/codemap.md`
- `docs/02-development/developer-guide.md`
