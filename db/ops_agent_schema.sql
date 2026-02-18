-- Combined reference DDL for Ops Agent tables in fraud_gov schema
-- This file serves as the combined reference for all agent-owned tables

-- ops_agent_runs table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_runs (
    run_id UUID PRIMARY KEY,
    mode VARCHAR(20) NOT NULL,
    trigger_ref TEXT,
    model_mode VARCHAR(20),
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    llm_status VARCHAR(20),
    llm_error TEXT,
    llm_model TEXT,
    duration_ms DOUBLE PRECISION,
    stage_durations JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_feature_flags JSONB NOT NULL DEFAULT '{}'::jsonb,
    runtime_safeguards JSONB NOT NULL DEFAULT '{}'::jsonb,
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_transaction_embeddings table
-- Ops-agent-owned pgvector embeddings keyed by TM transaction PK id.
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_transaction_embeddings (
    transaction_id UUID PRIMARY KEY REFERENCES fraud_gov.transactions(id) ON DELETE CASCADE,
    embedding vector(1024) NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_insights table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_insights (
    insight_id UUID PRIMARY KEY,
    transaction_pk_id UUID,
    transaction_id UUID NOT NULL,
    severity VARCHAR(20) NOT NULL,
    insight_summary TEXT NOT NULL,
    insight_type TEXT NOT NULL,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    model_mode VARCHAR(20) NOT NULL DEFAULT 'deterministic',
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_evidence table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_evidence (
    evidence_id UUID PRIMARY KEY,
    insight_id UUID NOT NULL REFERENCES fraud_gov.ops_agent_insights(insight_id),
    evidence_kind VARCHAR(50) NOT NULL,
    evidence_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_recommendations table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_recommendations (
    recommendation_id UUID PRIMARY KEY,
    insight_id UUID NOT NULL REFERENCES fraud_gov.ops_agent_insights(insight_id),
    recommendation_type VARCHAR(50) NOT NULL,
    recommendation_payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_rule_drafts table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_rule_drafts (
    rule_draft_id UUID PRIMARY KEY,
    recommendation_id UUID NOT NULL REFERENCES fraud_gov.ops_agent_recommendations(recommendation_id),
    draft_package_version TEXT NOT NULL,
    draft_payload JSONB NOT NULL,
    export_status VARCHAR(20) NOT NULL DEFAULT 'NOT_EXPORTED',
    exported_to TEXT,
    exported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_audit_log table (append-only)
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_audit_log (
    audit_id UUID PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,
    performed_by TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_transaction_id ON fraud_gov.ops_agent_insights(transaction_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_severity ON fraud_gov.ops_agent_insights(severity);
CREATE INDEX IF NOT EXISTS idx_ops_agent_evidence_insight_id ON fraud_gov.ops_agent_evidence(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_status_created ON fraud_gov.ops_agent_recommendations(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_insight_id ON fraud_gov.ops_agent_recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_recommendation_id ON fraud_gov.ops_agent_rule_drafts(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_audit_log_entity ON fraud_gov.ops_agent_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_runs_status ON fraud_gov.ops_agent_runs(status);

-- Grants (to be adjusted based on environment)
-- GRANT SELECT ON fraud_gov.transactions TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_rule_matches TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_reviews TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.analyst_notes TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_cases TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.cases TO fraud_gov_app_user;
