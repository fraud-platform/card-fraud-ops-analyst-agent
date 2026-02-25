# ADR-007: Investigation Memory Model and Knowledge Management

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Runtime and Intelligence ADR
**Related:** ADR-001, ADR-002, ADR-003, ADR-006

---

# 1. Context

Agent intelligence depends on memory.

Without memory, the agent behaves stateless and cannot improve investigation quality.

This ADR defines the memory model for the fraud investigation agent.

---

# 2. Memory Types Overview

The agent will maintain three types of memory:

1. Short-Term Memory (Working Memory)
2. Long-Term Memory (Investigation History)
3. Vector Memory (Semantic Knowledge)

---

# 3. Short-Term Memory

Short-term memory is the InvestigationState.

Stored in PostgreSQL.

Contains:

- context
- evidence
- tool outputs
- hypotheses
- recommendations

Lifetime:

Single investigation.

---

# 4. Long-Term Memory

Long-term memory stores historical investigations.

Used for:

- audit
- replay
- analytics
- model improvement

Stored in PostgreSQL.

---

# 5. Vector Memory

Vector memory stores semantic representations.

Used for:

- similarity search
- pattern detection

Stored in vector database.

Example options:

- PostgreSQL pgvector
- Pinecone
- Weaviate
- Milvus

---

# 6. Vector Memory Schema

Example:

```
CREATE TABLE investigation_embeddings (

    investigation_id UUID,

    embedding VECTOR(1536),

    metadata JSONB

);
```

---

# 7. Memory Write Flow

After investigation completes:

- Save investigation state
- Generate embedding
- Store embedding

---

# 8. Memory Read Flow

During investigation:

- Query similar investigations
- Retrieve relevant evidence

---

# 9. Memory Integration with Tools

SimilarityTool uses vector memory.

ContextTool uses long-term memory.

---

# 10. Memory Retention Policy

Retention configurable.

Example:

```
RETENTION_DAYS = 3650
```

---

# 11. Memory Performance Optimization

Use caching for frequent queries.

---

# 12. Privacy and Compliance

Sensitive data encrypted.

PII access restricted.

---

# 13. Memory Scaling

Vector database can scale horizontally.

---

# 14. Failure Recovery

Memory persisted before completion.

---

# 15. Observability

Track memory read/write latency.

---

# 16. Expected Outcome

Agent gains historical awareness and improved investigation capability.

---

# 17. Future Enhancements

Knowledge graphs

Automated learning

---

# 18. Final Decision

Agent will implement multi-layer memory model using PostgreSQL and vector database.
