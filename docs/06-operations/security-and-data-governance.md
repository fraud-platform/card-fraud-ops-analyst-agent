# Security and Data Governance

## Policy Summary

- Transaction Management data remains source of truth.
- PAN-equivalent data is already hashed/tokenized in TM and must remain so.
- Ops Agent must not require raw PAN handling.

## LLM Data Boundary

Even with hashed PAN, outbound payloads to LLM providers must be policy-filtered.

### Allowed in prompts

- Stable pseudonymous identifiers for correlation:
  - `card_token`/hashed card identifier
  - `merchant_id`
  - `device_hash`
- Derived features and aggregate statistics.
- Risk and decision metadata required for explanation.

### Blocked in prompts

- Raw payload dumps.
- Direct customer identity fields.
- Precise personal contact fields.
- Any field not explicitly allowlisted.

## Governance Controls

- All recommendation state changes audited.
- All draft exports audited.
- Policy violations logged and alertable.
- Retention and archival policy enforced.

## Access Controls

- Least privilege database roles.
- Scope-based API authorization.
- Service-to-service credentials per environment.
