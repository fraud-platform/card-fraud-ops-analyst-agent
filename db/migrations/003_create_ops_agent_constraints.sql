-- Migration 003: Create constraints for Ops Agent tables (Agentic Architecture)

-- Add foreign key constraints for investigation state
ALTER TABLE fraud_gov.ops_agent_investigation_state
    ADD CONSTRAINT fk_state_investigation
    FOREIGN KEY (investigation_id) REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE;

-- Add foreign key constraints for tool execution log
ALTER TABLE fraud_gov.ops_agent_tool_execution_log
    ADD CONSTRAINT fk_tool_log_investigation
    FOREIGN KEY (investigation_id) REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE CASCADE;

-- Add foreign key constraints for evidence
ALTER TABLE fraud_gov.ops_agent_evidence
    ADD CONSTRAINT fk_evidence_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id);

-- Add foreign key constraints for recommendations
ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT fk_recommendation_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id);

ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT fk_recommendation_investigation
    FOREIGN KEY (investigation_id) REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL;

-- Add foreign key constraints for rule drafts
ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT fk_rule_draft_recommendation
    FOREIGN KEY (recommendation_id) REFERENCES fraud_gov.ops_agent_recommendations(recommendation_id);

ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT fk_rule_draft_investigation
    FOREIGN KEY (investigation_id) REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL;

-- Add foreign key for insights -> investigations
ALTER TABLE fraud_gov.ops_agent_insights
    ADD CONSTRAINT fk_insight_investigation
    FOREIGN KEY (investigation_id) REFERENCES fraud_gov.ops_agent_investigations(id) ON DELETE SET NULL;
