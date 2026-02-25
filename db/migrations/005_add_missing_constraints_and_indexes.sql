-- Migration 005: Add missing constraints and indexes for agentic architecture

-- 1. Add CASCADE rules to existing foreign keys
ALTER TABLE fraud_gov.ops_agent_evidence
    DROP CONSTRAINT IF EXISTS fk_evidence_insight;

ALTER TABLE fraud_gov.ops_agent_evidence
    ADD CONSTRAINT fk_evidence_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id)
    ON DELETE CASCADE;

ALTER TABLE fraud_gov.ops_agent_recommendations
    DROP CONSTRAINT IF EXISTS fk_recommendation_insight;

ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT fk_recommendation_insight
    FOREIGN KEY (insight_id) REFERENCES fraud_gov.ops_agent_insights(insight_id)
    ON DELETE CASCADE;

ALTER TABLE fraud_gov.ops_agent_rule_drafts
    DROP CONSTRAINT IF EXISTS fk_rule_draft_recommendation;

ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT fk_rule_draft_recommendation
    FOREIGN KEY (recommendation_id) REFERENCES fraud_gov.ops_agent_recommendations(recommendation_id)
    ON DELETE CASCADE;

-- 2. Add CHECK constraints for conditional NOT NULL
ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT chk_recommendation_acknowledged
    CHECK (
        (status NOT IN ('ACKNOWLEDGED', 'REJECTED', 'EXPORTED')) OR
        (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)
    );

ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT chk_rule_draft_exported
    CHECK (
        (export_status != 'EXPORTED') OR
        (exported_to IS NOT NULL AND exported_at IS NOT NULL)
    );

-- 3. Add composite index for worklist query optimization
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_status_severity_created
ON fraud_gov.ops_agent_recommendations(status, created_at DESC)
INCLUDE (insight_id);

-- 4. Add partial index for OPEN recommendations only
CREATE INDEX IF NOT EXISTS idx_ops_agent_recommendations_open_created
ON fraud_gov.ops_agent_recommendations(created_at DESC)
WHERE status = 'OPEN';

-- 5. Add partial index for active investigations (IN_PROGRESS, PENDING)
CREATE INDEX IF NOT EXISTS idx_ops_agent_investigations_active
ON fraud_gov.ops_agent_investigations(started_at DESC)
WHERE status IN ('IN_PROGRESS', 'PENDING');

-- 6. Add unique constraint for active investigation per transaction
CREATE UNIQUE INDEX IF NOT EXISTS uq_investigations_active_transaction
ON fraud_gov.ops_agent_investigations(transaction_id)
WHERE status IN ('IN_PROGRESS', 'PENDING');
