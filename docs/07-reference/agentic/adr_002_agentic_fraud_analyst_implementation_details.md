# ADR-002: Agentic Fraud Analyst Implementation Details

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Implementation ADR
**Related:** ADR-001-Agentic-Fraud-Analyst-Architecture

---

# 1. Context

ADR-001 defined the architectural decision to migrate to a LangGraph-based agentic architecture.

This document defines the detailed implementation plan including:

- Database schema
- Persistence model
- Tool execution logging
- Observability
- Migration rollout strategy
- Failure handling
- Production hardening

---

# 2. Persistence Architecture

Persistence is required for:

- Investigation state tracking
- Auditability
- Replayability
- Failure recovery

PostgreSQL will be used as the primary state store.

Optional caching layer: Redis

---

# 3. PostgreSQL Schema

## 3.1 investigations

Tracks investigation lifecycle.

```
CREATE TABLE investigations (

    investigation_id UUID PRIMARY KEY,

    transaction_id TEXT NOT NULL,

    status TEXT NOT NULL,

    priority TEXT,

    created_at TIMESTAMP DEFAULT NOW(),

    updated_at TIMESTAMP DEFAULT NOW()

);
```

---

## 3.2 investigation_state

Stores full serialized agent state.

```
CREATE TABLE investigation_state (

    investigation_id UUID PRIMARY KEY,

    state JSONB NOT NULL,

    version INTEGER DEFAULT 1,

    updated_at TIMESTAMP DEFAULT NOW()

);
```

---

## 3.3 tool_execution_log

Tracks every tool invocation.

```
CREATE TABLE tool_execution_log (

    execution_id UUID PRIMARY KEY,

    investigation_id UUID,

    tool_name TEXT,

    input JSONB,

    output JSONB,

    execution_time_ms INTEGER,

    created_at TIMESTAMP DEFAULT NOW()

);
```

---

## 3.4 recommendations

```
CREATE TABLE recommendations (

    recommendation_id UUID PRIMARY KEY,

    investigation_id UUID,

    recommendation JSONB,

    confidence_score FLOAT,

    created_at TIMESTAMP DEFAULT NOW()

);
```

---

## 3.5 audit_log

```
CREATE TABLE audit_log (

    audit_id UUID PRIMARY KEY,

    investigation_id UUID,

    event_type TEXT,

    event_data JSONB,

    created_at TIMESTAMP DEFAULT NOW()

);
```

---

# 4. Persistence Implementation

Example persistence layer:

```
class PostgresStateStore:

    def save_state(self, investigation_id, state):

        query = """
        INSERT INTO investigation_state (investigation_id, state)
        VALUES (%s, %s)
        ON CONFLICT (investigation_id)
        DO UPDATE SET state = %s
        """

    def load_state(self, investigation_id):

        query = "SELECT state FROM investigation_state WHERE investigation_id = %s"
```

---

# 5. Tool Execution Logging

Every tool execution must be logged.

Example:

```
def execute_tool(tool, state):

    start = now()

    output = tool.execute(state)

    end = now()

    log_execution(tool.name, state, output, end-start)

    return output
```

This enables:

- audit
- replay
- debugging

---

# 6. Observability

OpenTelemetry will be used.

Example:

```
with tracer.start_as_current_span("pattern_tool"):

    result = pattern_tool.execute(state)
```

Exporters:

- Jaeger
- Prometheus
- Grafana

---

# 7. Failure Recovery

State is persisted after every step.

If system crashes:

```
state = load_state(investigation_id)

graph.resume(state)
```

This provides fault tolerance.

---

# 8. Migration Rollout Strategy

## Phase 1

Deploy agent alongside existing pipeline.

Run in shadow mode.

---

## Phase 2

Compare outputs.

Validate accuracy.

---

## Phase 3

Enable agent for limited traffic.

---

## Phase 4

Full production rollout.

---

# 9. Production Hardening

## Required safeguards

Max steps per investigation

Example:

```
MAX_STEPS = 20
```

Timeout per investigation

Example:

```
TIMEOUT_SECONDS = 30
```

---

# 10. Retry Strategy

Retry transient failures.

```
retry(tool.execute, retries=3)
```

---

# 11. Redis Caching (Optional)

Cache similarity search results.

Benefits:

- lower latency
- lower DB load

---

# 12. Deployment Architecture

```
API Server

Agent Runtime

PostgreSQL

Redis

LLM Provider
```

---

# 13. Monitoring Metrics

Track:

- investigation latency
- tool latency
- failure rate
- planner accuracy

---

# 14. Security

Sensitive data must be encrypted.

Use TLS.

Restrict DB access.

---

# 15. Testing Strategy

Unit tests

Integration tests

Replay tests

Load tests

---

# 16. Expected Outcome

Fully production-ready agentic fraud investigation system with:

- persistence
- auditability
- fault tolerance
- observability

---

# 17. Future Enhancements

Multi-agent architecture

Self-learning models

Automated pattern discovery

---

# 18. Final Implementation Outcome

System will provide production-grade autonomous fraud investigation capabilities while maintaining safety and auditability.
