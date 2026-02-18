-- Migration 001: Create Ops Agent tables
-- Creates all 6 agent-owned tables in fraud_gov schema

-- ops_agent_runs table
CREATE TABLE fraud_gov.ops_agent_runs (
    run_id UUID PRIMARY KEY,
    mode VARCHAR(20) NOT NULL,
    trigger_ref TEXT,
    started_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    completed_at TIMESTAMPTZ,
    status VARCHAR(20) NOT NULL DEFAULT 'RUNNING',
    error_summary TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_insights table
CREATE TABLE fraud_gov.ops_agent_insights (
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
CREATE TABLE fraud_gov.ops_agent_evidence (
    evidence_id UUID PRIMARY KEY,
    insight_id UUID NOT NULL,
    evidence_kind VARCHAR(50) NOT NULL,
    evidence_payload JSONB NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_recommendations table
CREATE TABLE fraud_gov.ops_agent_recommendations (
    recommendation_id UUID PRIMARY KEY,
    insight_id UUID NOT NULL,
    recommendation_type VARCHAR(50) NOT NULL,
    recommendation_payload JSONB NOT NULL,
    status VARCHAR(20) NOT NULL DEFAULT 'OPEN',
    acknowledged_by TEXT,
    acknowledged_at TIMESTAMPTZ,
    idempotency_key VARCHAR(64) UNIQUE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_rule_drafts table
CREATE TABLE fraud_gov.ops_agent_rule_drafts (
    rule_draft_id UUID PRIMARY KEY,
    recommendation_id UUID NOT NULL,
    draft_package_version TEXT NOT NULL,
    draft_payload JSONB NOT NULL,
    export_status VARCHAR(20) NOT NULL DEFAULT 'NOT_EXPORTED',
    exported_to TEXT,
    exported_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_audit_log table (append-only)
CREATE TABLE fraud_gov.ops_agent_audit_log (
    audit_id UUID PRIMARY KEY,
    entity_type TEXT NOT NULL,
    entity_id UUID NOT NULL,
    action TEXT NOT NULL,
    performed_by TEXT NOT NULL,
    old_value JSONB,
    new_value JSONB,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);
