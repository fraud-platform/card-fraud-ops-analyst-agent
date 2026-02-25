-- Migration 006: set agentic as canonical model_mode for insights

ALTER TABLE fraud_gov.ops_agent_insights
    ALTER COLUMN model_mode SET DEFAULT 'agentic';

UPDATE fraud_gov.ops_agent_insights
SET model_mode = 'agentic'
WHERE model_mode IN ('deterministic', 'hybrid');
