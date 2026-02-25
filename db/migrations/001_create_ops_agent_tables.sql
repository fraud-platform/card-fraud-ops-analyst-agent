-- Migration 001: Create Ops Agent tables (Agentic Architecture)
-- Creates all agent-owned tables in fraud_gov schema for LangGraph runtime

-- ops_agent_investigations table (renamed from ops_agent_runs)
CREATE TABLE fraud_gov.ops_agent_investigations (
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
CREATE TABLE fraud_gov.ops_agent_investigation_state (
    investigation_id UUID PRIMARY KEY,
    state JSONB NOT NULL DEFAULT '{}'::jsonb,
    version INTEGER NOT NULL DEFAULT 1,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_tool_execution_log table
CREATE TABLE fraud_gov.ops_agent_tool_execution_log (
    log_id UUID PRIMARY KEY,
    investigation_id UUID NOT NULL,
    tool_name VARCHAR(50) NOT NULL,
    step_number INTEGER NOT NULL,
    input_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    output_summary JSONB NOT NULL DEFAULT '{}'::jsonb,
    execution_time_ms INTEGER NOT NULL,
    status VARCHAR(20) NOT NULL,
    error_message TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_transaction_embeddings table (pgvector)
CREATE TABLE fraud_gov.ops_agent_transaction_embeddings (
    transaction_id UUID PRIMARY KEY,
    embedding vector(1024) NOT NULL,
    model_name TEXT NOT NULL,
    metadata JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- ops_agent_insights table
CREATE TABLE fraud_gov.ops_agent_insights (
    insight_id UUID PRIMARY KEY,
    investigation_id UUID,
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
    investigation_id UUID,
    insight_id UUID,
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
CREATE TABLE fraud_gov.ops_agent_rule_drafts (
    rule_draft_id UUID PRIMARY KEY,
    investigation_id UUID,
    recommendation_id UUID,
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
