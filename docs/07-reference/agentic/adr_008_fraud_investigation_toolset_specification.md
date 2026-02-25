# ADR-008: Fraud Investigation Toolset Specification

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Intelligence and Capability ADR
**Related:** ADR-001, ADR-003, ADR-004, ADR-007

---

# 1. Context

The effectiveness of the fraud agent depends on the quality and completeness of investigation tools.

Tools provide deterministic analysis capabilities used by the agent planner.

This ADR defines the standard fraud investigation toolset.

---

# 2. Tool Design Principles

All tools must be:

- deterministic
- idempotent
- auditable
- fast (<100ms target where possible)

Tools must operate independently.

---

# 3. Core Tool Categories

The agent will include the following core investigation tools:

1. Context Retrieval Tool
2. Similarity Analysis Tool
3. Velocity Analysis Tool
4. Merchant Risk Analysis Tool
5. Geo Risk Analysis Tool
6. Behavioral Analysis Tool
7. Rule Effectiveness Tool
8. Recommendation Tool
9. Rule Draft Tool

---

# 4. Context Retrieval Tool

Purpose:

Retrieve transaction details.

Data sources:

- transaction DB
- user profile DB

Output:

- enriched transaction context

---

# 5. Similarity Analysis Tool

Purpose:

Find similar fraud transactions.

Uses:

Vector database

Output:

- similar investigations

---

# 6. Velocity Analysis Tool

Purpose:

Detect abnormal transaction frequency.

Example metrics:

transactions per minute

transactions per hour

---

# 7. Merchant Risk Tool

Purpose:

Evaluate merchant fraud risk.

Data:

merchant fraud rate

chargeback history

---

# 8. Geo Risk Tool

Purpose:

Detect geographic anomalies.

Example:

impossible travel

---

# 9. Behavioral Analysis Tool

Purpose:

Compare transaction with user behavior baseline.

---

# 10. Rule Effectiveness Tool

Purpose:

Evaluate effectiveness of fraud rules.

---

# 11. Recommendation Tool

Purpose:

Generate investigation recommendation.

---

# 12. Rule Draft Tool

Purpose:

Generate fraud detection rule.

---

# 13. Tool Execution Order Example

Example investigation sequence:

Context → Similarity → Velocity → Merchant → Geo → Behavior → Recommendation → Rule Draft

---

# 14. Tool Performance Requirements

Target latency per tool:

< 100ms

---

# 15. Tool Failure Handling

Retry transient failures.

Log failures.

---

# 16. Observability

Track tool latency.

Track tool usage frequency.

---

# 17. Expected Outcome

Complete fraud investigation capability.

---

# 18. Future Enhancements

ML-based tools

Real-time streaming tools

---

# 19. Final Decision

Agent will implement standardized fraud investigation toolset defined in this ADR.
