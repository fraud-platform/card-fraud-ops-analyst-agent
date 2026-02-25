-- Combined reference DDL for Ops Agent tables in fraud_gov schema
-- This file serves as the combined reference for all agent-owned tables
-- AGENTIC ARCHITECTURE: LangGraph-based investigation runtime

-- ops_agent_investigations table (renamed from ops_agent_runs)
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_investigations (
    id UUID PRIMARY KEY,
    transaction_id UUID NOT NULL,
    mode VARCHAR(20) NOT NULL DEFAULT 'FULL',
    status VARCHAR(20) NOT NULL DEFAULT 'PENDING',
    priority VARCHAR(20) NOT NULL DEFAULT 'MEDIUM',
    severity VARCHAR(20) NOT NULL DEFAULT 'LOW',
    final_confidence DOUBLE PRECISION DEFAULT 0.0,
    step_count INTEGER NOT NULL DEFAULT 0,
    max_steps INTEGER NOT NULL DEFAULT 20,
    planner_model TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    duration_ms DOUBLE PRECISION,
    error TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_investigation_state table (JSONB state persistence for resume)
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_investigation_state (
    investigation_id UUID PRIMARY KEY REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_tool_execution_log table (audit log for tool executions)
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_tool_execution_log (
    log_id UUID PRIMARY KEY,
    investigation_id UUID NOT NULL REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE,
    tool_name VARCHAR(50) NOT NULL,
    step_number INTEGER NOT NULL,
    input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_time_ms INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_transaction_embeddings table (pgvector for similarity)
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_transaction_embeddings (
    transaction_id UUID PRIMARY KEY REFERENCES fraud_gov.transactions(id) ON DELETE CASCADE,
    embedding vector(1024) NOT NULL,
    model_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_insights table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_insights (
    insight_id UUID PRIMARY KEY,
    investigation_id UUID REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL,
    transaction_pk_id UUID,
    transaction_id UUID NOT NULL,
    severity VARCHAR(20) NOT NULL,
    summary TEXT NOT NULL,
    insight_type TEXT NOT NULL,
    model_mode VARCHAR(20) NOT NULL DEFAULT 'agentic',
    confidence_score DOUBLE PRECISION DEFAULT 0.0,
    generated_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
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
    investigation_id UUID REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL,
    insight_id UUID REFERENCES fraud_gov.ops_agent_insights(insight_id),
    type VARCHAR(50) NOT NULL,
    priority INTEGER NOT NULL DEFAULT 3,
    title TEXT NOT NULL,
    impact TEXT NOT NULL,
    payload JSONB NOT NULL,
    signature_hash VARCHAR(64),
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_rule_drafts table
CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_rule_drafts (
    rule_draft_id UUID PRIMARY KEY,
    investigation_id UUID REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL,
    recommendation_id UUID REFERENCES fraud_gov.ops_agent_recommendations(recommendation_id),
    rule_name TEXT NOT NULL,
    rule_description TEXT NOT NULL,
    conditions JSONB NOT NULL DEFAULT '[]'::jsonb,
    thresholds JSONB NOT NULL DEFAULT '{}'::jsonb,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
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
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_transaction_id ON fraud_gov.ops_agent_investigations(transaction_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_status ON fraud_gov.ops_agent_investigations(status);
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_started_at ON fraud_gov.ops_agent_investigations(started_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigation_state_updated ON fraud_gov.ops_agent_investigation_state(updated_at);
CREATE INDEX IF NOT EXISTS idx_ops_agent_tool_log_investigation ON fraud_gov.ops_agent_tool_execution_log(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_tool_log_tool_name ON fraud_gov.ops_agent_tool_execution_log(tool_name);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_transaction_id ON fraud_gov.ops_agent_insights(transaction_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_severity ON fraud_gov.ops_agent_insights(severity);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_investigation ON fraud_gov.ops_agent_insights(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_evidence_insight_id ON fraud_gov.ops_agent_evidence(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_status_created ON fraud_gov.ops_agent_recommendations(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_insight_id ON fraud_gov.ops_agent_recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_investigation ON fraud_gov.ops_agent_recommendations(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_recommendation_id ON fraud_gov.ops_agent_rule_drafts(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_investigation ON fraud_gov.ops_agent_rule_drafts(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_audit_log_entity ON fraud_gov.ops_agent_audit_log(entity_type, entity_id);

-- Grants (to be adjusted based on environment)
-- GRANT SELECT ON fraud_gov.transactions TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_rule_matches TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_reviews TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.analyst_notes TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.transaction_cases TO fraud_gov_app_user;
-- GRANT SELECT ON fraud_gov.cases TO fraud_gov_app_user;
