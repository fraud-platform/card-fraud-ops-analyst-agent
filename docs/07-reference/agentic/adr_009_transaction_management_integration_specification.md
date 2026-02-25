# ADR-009: Transaction Management Integration Specification

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Integration ADR
**Related:** ADR-001, ADR-002, ADR-008

---

# 1. Context

Transaction Management Service is the system of record for all transaction data.

It persists transaction data in PostgreSQL.

Fraud Investigation Agent requires access to transaction data for investigation.

This ADR defines the integration model between Fraud Agent and Transaction Management Service.

---

# 2. Integration Principle

Fraud Agent MUST access transaction data via Transaction Management API.

Fraud Agent MUST NOT access core transaction database directly.

Exception:

Agent may access read replicas if required for performance.

---

# 3. Architecture

```
Rule Engine
   ↓
Transaction Management Service
   ↓
PostgreSQL (Source of Truth)
   ↑
Transaction Management API
   ↑
Fraud Investigation Agent
```

---

# 4. Required API Endpoints

## 4.1 Get Transaction

```
GET /transactions/{transaction_id}
```

Response:

```
{
  transaction_id,
  user_id,
  merchant_id,
  amount,
  currency,
  timestamp,
  location,
  device_info
}
```

---

## 4.2 Get User Transactions

```
GET /users/{user_id}/transactions?from=&to=
```

Used for velocity analysis.

---

## 4.3 Get Merchant Profile

```
GET /merchants/{merchant_id}/profile
```

---

## 4.4 Get User Profile

```
GET /users/{user_id}/profile
```

---

# 5. Latency Requirements

Target latency:

< 50ms per API call

---

# 6. Reliability Requirements

API availability:

99.9% minimum

---

# 7. Security Requirements

API must use:

- authentication
- authorization
- TLS encryption

---

# 8. Agent Context Tool Integration

ContextTool will call Transaction Management API.

Example:

```
transaction = api.get_transaction(transaction_id)
```

---

# 9. Failure Handling

Retry transient failures.

Fallback mechanisms allowed.

---

# 10. Scaling Model

Transaction Management Service must support concurrent agent requests.

---

# 11. Read Replica Option

Optional read replica may be used.

---

# 12. Observability

Track API latency.

Track API errors.

---

# 13. Expected Outcome

Clean separation of responsibilities.

---

# 14. Final Decision

Fraud Agent will integrate with Transaction Management Service via API-first model.
