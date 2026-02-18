-- Migration 003: Create constraints for Ops Agent tables

-- Add foreign key constraints
ALTER TABLE fraud_gov.ops_agent_evidence
    ADD CONSTRAINT fk_evidence_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id);

ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT fk_recommendation_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id);

ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT fk_rule_draft_recommendation
    FOREIGN KEY (recommendation_id) REFERENCES fraud_gov.ops_agent_recommendations(recommendation_id);
