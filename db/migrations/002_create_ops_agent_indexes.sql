-- Migration 002: Create indexes for Ops Agent tables (Agentic Architecture)

-- Investigation indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_transaction_id ON fraud_gov.ops_agent_investigations(transaction_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_status ON fraud_gov.ops_agent_investigations(status);
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_started_at ON fraud_gov.ops_agent_investigations(started_at DESC);

-- State store index
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigation_state_updated ON fraud_gov.ops_agent_investigation_state(updated_at);

-- Tool execution log indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_tool_log_investigation ON fraud_gov.ops_agent_tool_execution_log(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_tool_log_tool_name ON fraud_gov.ops_agent_tool_execution_log(tool_name);

-- Insight indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_transaction_id ON fraud_gov.ops_agent_insights(transaction_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_severity ON fraud_gov.ops_agent_insights(severity);
CREATE INDEX IF NOT EXISTS idx_ops_agent_insights_investigation ON fraud_gov.ops_agent_insights(investigation_id);

-- Evidence indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_evidence_insight_id ON fraud_gov.ops_agent_evidence(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_evidence_kind ON fraud_gov.ops_agent_evidence(evidence_kind);

-- Recommendation indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_status_created ON fraud_gov.ops_agent_recommendations(status, created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_insight_id ON fraud_gov.ops_agent_recommendations(insight_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_investigation ON fraud_gov.ops_agent_recommendations(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_idempotency ON fraud_gov.ops_agent_recommendations(idempotency_key);

-- Rule draft indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_recommendation_id ON fraud_gov.ops_agent_rule_drafts(recommendation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_investigation ON fraud_gov.ops_agent_rule_drafts(investigation_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_rule_drafts_export_status ON fraud_gov.ops_agent_rule_drafts(export_status);

-- Audit log indexes
CREATE INDEX IF NOT EXISTS idx_ops_agent_audit_log_entity ON fraud_gov.ops_agent_audit_log(entity_type, entity_id);
CREATE INDEX IF NOT EXISTS idx_ops_agent_audit_log_created_at ON fraud_gov.ops_agent_audit_log(created_at DESC);
CREATE INDEX IF NOT EXISTS idx_ops_agent_audit_log_performed_by ON fraud_gov.ops_agent_audit_log(performed_by);
