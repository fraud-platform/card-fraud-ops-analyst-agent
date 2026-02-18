# Database Access and Roles

## Design Decision

Ops Agent uses `fraud_gov` as the shared schema and source-of-truth domain for analyst operations.
No separate schema is required in v1.

## Role Model

### Read responsibilities

Ops Agent read role must be able to read:
- `fraud_gov.transactions`
- `fraud_gov.transaction_rule_matches`
- `fraud_gov.transaction_reviews`
- `fraud_gov.analyst_notes`
- `fraud_gov.transaction_cases`

### Write responsibilities

Ops Agent write role must only write to agent-owned tables:
- `fraud_gov.ops_agent_insights`
- `fraud_gov.ops_agent_evidence`
- `fraud_gov.ops_agent_recommendations`
- `fraud_gov.ops_agent_rule_drafts`
- `fraud_gov.ops_agent_runs`
- `fraud_gov.ops_agent_audit_log`

## Privilege Constraints

- No insert/update/delete on core TM truth tables.
- No schema/object creation in production runtime role.
- Explicit grants only; no broad `ALL PRIVILEGES` usage.

## Audit Requirements

- Every recommendation state transition must be auditable.
- Every generated rule draft must record source recommendation and analyst actor.
