-- Migration 002: Create indexes for Ops Agent tables

-- Indexes for ops_agent_insights
CREATE INDEX idx_ops_agent_insights_transaction_id ON fraud_gov.ops_agent_insights(transaction_id);
CREATE INDEX idx_ops_agent_insights_severity ON fraud_gov.ops_agent_insights(severity);
CREATE INDEX idx_ops_agent_insights_generated_at ON fraud_gov.ops_agent_insights(generated_at DESC);

-- Indexes for ops_agent_evidence
CREATE INDEX idx_ops_agent_evidence_insight_id ON fraud_gov.ops_agent_evidence(insight_id);
CREATE INDEX idx_ops_agent_evidence_kind ON fraud_gov.ops_agent_evidence(evidence_kind);

-- Indexes for ops_agent_recommendations (keyset pagination)
CREATE INDEX idx_ops_agent_recommendations_status_created ON fraud_gov.ops_agent_recommendations(status, created_at DESC);
CREATE INDEX idx_ops_agent_recommendations_insight_id ON fraud_gov.ops_agent_recommendations(insight_id);
CREATE INDEX idx_ops_agent_recommendations_idempotency ON fraud_gov.ops_agent_recommendations(idempotency_key);

-- Indexes for ops_agent_rule_drafts
CREATE INDEX idx_ops_agent_rule_drafts_recommendation_id ON fraud_gov.ops_agent_rule_drafts(recommendation_id);
CREATE INDEX idx_ops_agent_rule_drafts_export_status ON fraud_gov.ops_agent_rule_drafts(export_status);

-- Indexes for ops_agent_audit_log
CREATE INDEX idx_ops_agent_audit_log_entity ON fraud_gov.ops_agent_audit_log(entity_type, entity_id);
CREATE INDEX idx_ops_agent_audit_log_created_at ON fraud_gov.ops_agent_audit_log(created_at DESC);
CREATE INDEX idx_ops_agent_audit_log_performed_by ON fraud_gov.ops_agent_audit_log(performed_by);

-- Indexes for ops_agent_runs
CREATE INDEX idx_ops_agent_runs_status ON fraud_gov.ops_agent_runs(status);
CREATE INDEX idx_ops_agent_runs_started_at ON fraud_gov.ops_agent_runs(started_at DESC);
