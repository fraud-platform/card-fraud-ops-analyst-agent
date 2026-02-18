-- Migration 005: Add missing constraints and indexes from code review
-- Addresses P0/P1 database issues from review

-- 1. Add CASCADE rules to existing foreign keys
-- Drop and recreate with ON DELETE CASCADE for proper cleanup
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

-- 2. Add unique constraint on ops_agent_runs.trigger_ref
-- Prevents duplicate runs for same transaction/case combination
ALTER TABLE fraud_gov.ops_agent_runs
    ADD CONSTRAINT uq_runs_trigger_ref UNIQUE (trigger_ref);

-- 3. Add CHECK constraints for conditional NOT NULL
-- Ensures data quality for status-specific fields

-- For recommendations: acknowledged_by and acknowledged_at must be set when status changes
ALTER TABLE fraud_gov.ops_agent_recommendations
    ADD CONSTRAINT chk_recommendation_acknowledged
    CHECK (
        (status NOT IN ('ACKNOWLEDGED', 'REJECTED', 'EXPORTED')) OR
        (acknowledged_by IS NOT NULL AND acknowledged_at IS NOT NULL)
    );

-- For rule_drafts: exported_to and exported_at must be set when exported
ALTER TABLE fraud_gov.ops_agent_rule_drafts
    ADD CONSTRAINT chk_rule_draft_exported
    CHECK (
        (export_status != 'EXPORTED') OR
        (exported_to IS NOT NULL AND exported_at IS NOT NULL)
    );

-- 4. Add composite index for worklist query optimization
-- Covers (status, created_at) with insight_id included for JOIN performance
CREATE INDEX idx_ops_agent_recommendations_status_severity_created
ON fraud_gov.ops_agent_recommendations(status, created_at DESC)
INCLUDE (insight_id);

-- 5. Add partial index for OPEN recommendations only
-- More efficient than full index since worklist only cares about OPEN items
CREATE INDEX idx_ops_agent_recommendations_open_created
ON fraud_gov.ops_agent_recommendations(created_at DESC)
WHERE status = 'OPEN';

-- 6. Add partial index for active runs (RUNNING, PENDING)
-- Optimizes queries looking for active/in-progress runs
CREATE INDEX idx_ops_agent_runs_active
ON fraud_gov.ops_agent_runs(started_at DESC)
WHERE status IN ('RUNNING', 'PENDING');

-- Note: The FK constraint to fraud_gov.transactions is not added here
-- because ops_agent_insights uses transaction_id (business key) which is
-- the actual joining column. The transaction_pk_id column may be deprecated.
