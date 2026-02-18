# Domain and Data Model

## Domain Boundaries

### Source of truth domain (owned by TM)

- Transactions
- Rule matches
- Reviews
- Notes
- Cases

### Agent artifact domain (owned by Ops Agent)

- Insights
- Evidence
- Recommendations
- Rule draft packages
- Run telemetry
- Audit trail

## Shared Schema Strategy

All v1 tables remain in `fraud_gov`.

## Proposed Agent Tables

### `fraud_gov.ops_agent_insights`

- `insight_id` (UUID PK)
- `transaction_pk_id` (UUID FK -> `fraud_gov.transactions.id`)
- `transaction_id` (UUID business key)
- `severity` (`LOW|MEDIUM|HIGH|CRITICAL`)
- `insight_summary` (text)
- `insight_type` (text)
- `generated_at` (timestamptz)
- `model_mode` (`deterministic|hybrid`)

### `fraud_gov.ops_agent_evidence`

- `evidence_id` (UUID PK)
- `insight_id` (UUID FK)
- `evidence_kind` (`pattern|similarity|context|counter_evidence`)
- `evidence_payload` (jsonb)
- `created_at` (timestamptz)

### `fraud_gov.ops_agent_recommendations`

- `recommendation_id` (UUID PK)
- `insight_id` (UUID FK)
- `recommendation_type` (`review_priority|case_action|rule_candidate`)
- `recommendation_payload` (jsonb)
- `status` (`OPEN|ACKNOWLEDGED|REJECTED|EXPORTED`)
- `acknowledged_by` (text nullable)
- `acknowledged_at` (timestamptz nullable)
- `created_at` (timestamptz)

### `fraud_gov.ops_agent_rule_drafts`

- `rule_draft_id` (UUID PK)
- `recommendation_id` (UUID FK)
- `draft_package_version` (text)
- `draft_payload` (jsonb)
- `export_status` (`NOT_EXPORTED|EXPORTED|FAILED`)
- `exported_to` (text nullable)
- `exported_at` (timestamptz nullable)
- `created_at` (timestamptz)

### `fraud_gov.ops_agent_runs`

- `run_id` (UUID PK)
- `mode` (`quick|deep`)
- `trigger_ref` (text)
- `model_mode` (`deterministic|hybrid`)
- `started_at` (timestamptz)
- `completed_at` (timestamptz nullable)
- `status` (`RUNNING|SUCCESS|FAILED`)
- `llm_status` (`disabled|skipped|deterministic|success|fallback|failed`)
- `llm_error` (text nullable)
- `llm_model` (text nullable)
- `duration_ms` (double precision nullable)
- `stage_durations` (jsonb)
- `runtime_feature_flags` (jsonb)
- `runtime_safeguards` (jsonb)
- `error_summary` (text nullable)
- `conflict_matrix` (jsonb nullable)

### `fraud_gov.ops_agent_audit_log`

- `audit_id` (UUID PK)
- `entity_type` (text)
- `entity_id` (UUID)
- `action` (text)
- `performed_by` (text)
- `old_value` (jsonb nullable)
- `new_value` (jsonb nullable)
- `created_at` (timestamptz)

## Data Retention Guidelines

- Insights and recommendations: 180 days hot retention, archival after threshold.
- Audit logs: retain per governance policy (recommended >= 1 year).
- Rule draft artifacts: retain until superseded and archived.
