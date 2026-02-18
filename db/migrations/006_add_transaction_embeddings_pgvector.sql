-- Migration 006: Add ops-agent-owned transaction embeddings for pgvector similarity
--
-- IMPORTANT:
-- - Do NOT alter fraud_gov.transactions (owned by Transaction Management)
-- - This creates an ops-agent-owned table keyed by transaction_id

CREATE EXTENSION IF NOT EXISTS vector;

CREATE TABLE IF NOT EXISTS fraud_gov.ops_agent_transaction_embeddings (
    transaction_id UUID PRIMARY KEY REFERENCES fraud_gov.transactions(id) ON DELETE CASCADE,
    embedding vector(1024) NOT NULL,
    model_name TEXT NOT NULL,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Approximate cosine search index
CREATE INDEX IF NOT EXISTS idx_ops_agent_tx_embeddings_embedding
ON fraud_gov.ops_agent_transaction_embeddings
USING ivfflat (embedding vector_cosine_ops)
WITH (lists = 100);

-- App user needs to read and upsert embeddings
GRANT SELECT, INSERT, UPDATE ON fraud_gov.ops_agent_transaction_embeddings TO fraud_gov_app_user;
