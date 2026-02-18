-- Migration 009: Persist runtime feature/safeguard snapshots for audit replay

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS runtime_feature_flags JSONB NOT NULL DEFAULT '{}'::jsonb;

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS runtime_safeguards JSONB NOT NULL DEFAULT '{}'::jsonb;
