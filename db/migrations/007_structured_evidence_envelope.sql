-- Migration 007: Structured Evidence Envelope
--
-- IMPORTANT:
-- - Adds structured columns to ops_agent_evidence for queryability
-- - Adds conflict_matrix JSONB to ops_agent_runs

-- Add structured columns to evidence table
ALTER TABLE fraud_gov.ops_agent_evidence
ADD COLUMN IF NOT EXISTS category VARCHAR(100),
ADD COLUMN IF NOT EXISTS strength FLOAT CHECK (strength >= 0.0 AND strength <= 1.0),
ADD COLUMN IF NOT EXISTS timestamp TIMESTAMPTZ,
ADD COLUMN IF NOT EXISTS freshness_weight FLOAT CHECK (freshness_weight >= 0.0 AND freshness_weight <= 1.0),
ADD COLUMN IF NOT EXISTS related_transaction_ids TEXT[],
ADD COLUMN IF NOT EXISTS evidence_references JSONB;

-- Create indexes for queryability
CREATE INDEX IF NOT EXISTS idx_evidence_kind_category
ON fraud_gov.ops_agent_evidence(evidence_kind, category);

CREATE INDEX IF NOT EXISTS idx_evidence_strength
ON fraud_gov.ops_agent_evidence(strength DESC)
WHERE strength > 0.5;

CREATE INDEX IF NOT EXISTS idx_evidence_timestamp
ON fraud_gov.ops_agent_evidence(timestamp DESC);

CREATE INDEX IF NOT EXISTS idx_evidence_related_txns
ON fraud_gov.ops_agent_evidence USING GIN (related_transaction_ids);

-- Add conflict matrix to runs table
ALTER TABLE fraud_gov.ops_agent_runs
ADD COLUMN IF NOT EXISTS conflict_matrix JSONB;

CREATE INDEX IF NOT EXISTS idx_runs_conflict_score
ON fraud_gov.ops_agent_runs((CAST(conflict_matrix->>'overall_conflict_score' AS float)) DESC)
WHERE conflict_matrix IS NOT NULL;

-- Grant permissions
GRANT SELECT, INSERT, UPDATE ON fraud_gov.ops_agent_evidence TO fraud_gov_app_user;
GRANT SELECT, INSERT, UPDATE ON fraud_gov.ops_agent_runs TO fraud_gov_app_user;
