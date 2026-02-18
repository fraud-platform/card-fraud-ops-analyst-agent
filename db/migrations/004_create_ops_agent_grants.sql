-- Migration 004: Create grants for Ops Agent tables

-- Grant read/write on agent tables to app user
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fraud_gov TO fraud_gov_app_user;
GRANT SELECT, INSERT, UPDATE, DELETE ON ALL TABLES IN SCHEMA fraud_gov TO fraud_gov_analytics_user;

-- Grant read-only on TM tables to app user (for context building)
GRANT SELECT ON fraud_gov.transactions TO fraud_gov_app_user;
GRANT SELECT ON fraud_gov.transaction_rule_matches TO fraud_gov_app_user;
GRANT SELECT ON fraud_gov.transaction_reviews TO fraud_gov_app_user;
GRANT SELECT ON fraud_gov.analyst_notes TO fraud_gov_app_user;
GRANT SELECT ON fraud_gov.transaction_cases TO fraud_gov_app_user;

-- Audit log: INSERT only (no UPDATE/DELETE)
GRANT INSERT ON fraud_gov.ops_agent_audit_log TO fraud_gov_app_user;
GRANT SELECT ON fraud_gov.ops_agent_audit_log TO fraud_gov_app_user;
