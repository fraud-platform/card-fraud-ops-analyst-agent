-- Migration 008: Add run-level observability fields for detail endpoint auditability

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS model_mode VARCHAR(20);

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS llm_status VARCHAR(20);

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS llm_error TEXT;

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS llm_model TEXT;

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS duration_ms DOUBLE PRECISION;

ALTER TABLE fraud_gov.ops_agent_runs
    ADD COLUMN IF NOT EXISTS stage_durations JSONB NOT NULL DEFAULT '{}'::jsonb;
