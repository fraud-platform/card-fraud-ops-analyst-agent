# ADR-004: Agent Tool Interface and Contracts Specification

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Implementation ADR
**Related:** ADR-001, ADR-002, ADR-003

---

# 1. Context

Tools are the execution layer of the fraud agent.

Each tool performs deterministic operations.

---

# 2. Tool Responsibilities

Tools must:

- Accept InvestigationState
- Execute deterministic logic
- Return updated InvestigationState

Tools must NOT:

- Perform planning
- Call other tools

---

# 3. Tool Interface

```
class Tool:

    name: str

    description: str

    def execute(self, state):

        return updated_state
```

---

# 4. Tool Types

ContextTool

SimilarityTool

PatternTool

ReasoningTool

RecommendationTool

RuleDraftTool

---

# 5. Tool Registry

```
registry.register(tool)
```

---

# 6. Tool Safety Requirements

Tools must be:

- deterministic
- idempotent
- auditable

---

# 7. Tool Logging

All executions logged.

---

# 8. Tool Failure Handling

Retry transient failures.

---

# 9. Expected Outcome

Reliable execution layer.

---

# 10. Final Decision

All agent capabilities implemented as tools.
