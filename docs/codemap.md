# Code and Document Map

## Repository Layout

- `README.md` - top-level project purpose and constraints
- `AGENTS.md` - agent execution guardrails
- `CLAUDE.md` - project instructions and quick reference
- `DEVELOPER_GUIDE.md` - workflow for this planning phase
- `docs/` - canonical setup, architecture, API, deployment, and operations docs
- `/api/v1/metrics` - Prometheus scrape endpoint (requires `X-Metrics-Token`)

## Docs by Responsibility

- `docs/01-setup/` - onboarding and environment assumptions
- `docs/02-development/` - architecture, design, and performance patterns
- `docs/03-api/` - API and event contracts
- `docs/04-testing/` - validation strategy and acceptance matrix
- `docs/05-deployment/` - deployment design, configuration, and release gates
- `docs/06-operations/` - runbooks, observability, governance, and database operations
- `docs/07-reference/` - ADRs and cross-repo references

## Primary Design Documents

- Architecture: `docs/02-development/architecture.md`
- Data model: `docs/02-development/domain-and-data-model.md`
- API contract: `docs/03-api/ops-agent-api-contract-v1.md`
- Release gates: `docs/05-deployment/release-gates.md`
- Security policy: `docs/06-operations/security-and-data-governance.md`
- Security config: `docs/05-deployment/security-configuration.md`
- Performance patterns: `docs/02-development/performance-patterns.md`
- Database operations: `docs/06-operations/database-operations.md`
- ADR index: `docs/07-reference/overview.md`

## Complete Documentation Index

### 01-setup - Setup
- `local-setup.md` - Local development environment setup
- `doppler-secrets-setup.md` - Doppler secrets management
- `database-access-and-roles.md` - Database access and role configuration
- `auth0-setup-guide.md` - Auth0 tenant and API setup

### 02-development - Development
- `architecture.md` - System mission, principles, topology, service modules
- `domain-and-data-model.md` - Core entities, relationships, state transitions
- `agent-workflow-and-orchestration.md` - Pipeline orchestration and agent coordination
- `storage-and-migrations.md` - Schema design, migrations, indexing, SQL injection prevention
- `idempotency-and-replay.md` - Idempotency keys and replay protection
- `performance-patterns.md` - Parallel queries, caching, timeouts, best practices
- `app/templates/trace_viewer.py` - Self-contained HTML trace viewer template

### 03-api - API
- `openapi-outline.md` - OpenAPI specification overview
- `ops-agent-api-contract-v1.md` - API contract documentation
- `openapi.json` - Full OpenAPI specification
- `portal-integration.md` - Portal integration guide
- `rule-draft-package.schema.v1.json` - Rule draft package schema
- `insight-event.schema.v1.json` - Insight event schema
- `action-event.schema.v1.json` - Action event schema

### 04-testing - Testing
- `testing-strategy.md` - Testing strategy and approach
- `acceptance-test-matrix.md` - Acceptance test criteria
- `non-functional-test-plan.md` - Non-functional test planning

### 05-deployment - Deployment
- `platform-docker-integration.md` - Docker and platform integration
- `config-and-feature-flags.md` - Feature flags, LLM config, reload behavior
- `security-configuration.md` - CORS, JWT, authorization, security headers
- `release-gates.md` - Pre-release validation and approval process
- `production-readiness-checklist.md` - Production readiness validation

### 06-operations - Operations
- `database-operations.md` - Pool tuning, query security, maintenance, troubleshooting
- `runbooks.md` - Step-by-step operational procedures
- `observability.md` - Metrics, logs, traces, audit events
- `security-and-data-governance.md` - Access controls, audit logging, compliance
- `model-risk-and-prompt-governance.md` - LLM usage policies and testing
- `incidents-and-rollback.md` - Incident response and rollback procedures
- `performance-baselines.md` - Performance targets and alerting thresholds

### 07-reference - Reference
- `overview.md` - Reference documentation index
- `fraud-analyst-workflow.md` - Fraud analyst workflow documentation
- `auth-model.md` - Authentication and authorization model
- `0000-use-adr.md` - ADR template
- `0001-tm-as-source-of-truth.md` - Transaction Management as source of truth
- `0002-human-approval-finality.md` - Human approval finality policy
- `0003-fraud-gov-shared-schema-agent-tables.md` - Shared schema and agent tables
- `0005-redaction-and-pseudonym-policy.md` - Redaction and pseudonymization policy
- `0006-rule-draft-package-and-maker-checker-handoff.md` - Rule draft handoff process
- `0008-rollout-gating-and-slo-policy.md` - Rollout gating and SLO policy
- `agentic/README.md` - Agentic architecture ADR/TDD index
- `agentic/adr_001_agentic_fraud_analyst_architecture.md` - Agentic runtime architecture decision
- `agentic/tdd_001_master_transformation_plan.md` - Agentic transformation implementation plan

## Program Plan

- `07-reference/agentic/comprehensive-review-and-cleanup-plan.md` - Agentic modernization and cleanup plan
