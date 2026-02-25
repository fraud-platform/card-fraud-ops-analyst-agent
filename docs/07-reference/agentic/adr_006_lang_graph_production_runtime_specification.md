# ADR-006: LangGraph Production Runtime Specification

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Runtime Architecture ADR
**Related:** ADR-001, ADR-002, ADR-003, ADR-004, ADR-005

---

# 1. Context

ADR-001 through ADR-005 defined the architecture, planner, tools, persistence, and multi-agent evolution.

This ADR defines the production runtime model using LangGraph.

LangGraph will serve as the deterministic execution engine for the fraud investigation agent.

---

# 2. Runtime Responsibilities

LangGraph runtime will manage:

- Investigation execution lifecycle
- State transitions
- Planner invocation
- Tool execution
- Failure recovery
- Resume and replay

---

# 3. Runtime Execution Model

Execution follows a state machine model.

```
START
  ↓
Planner Node
  ↓
Tool Node
  ↓
State Update
  ↓
Planner Node
  ↓
... repeat
  ↓
Completion Node
  ↓
END
```

---

# 4. Node Definitions

## Planner Node

Responsibilities:

- Analyze state
- Select next tool

Input:

InvestigationState

Output:

next_action

---

## Tool Execution Node

Responsibilities:

- Execute selected tool
- Update state

---

## Completion Node

Responsibilities:

- Finalize investigation
- Persist final state

---

# 5. Graph Topology

```
planner → tool_executor → planner

planner → completion
```

Conditional edge determines completion.

---

# 6. LangGraph Implementation

Example:

```
from langgraph.graph import StateGraph

builder = StateGraph(InvestigationState)

builder.add_node("planner", planner_node)

builder.add_node("tool_executor", tool_node)

builder.add_node("completion", completion_node)

builder.set_entry_point("planner")

builder.add_conditional_edges(
    "planner",
    condition_function,
    {
        "execute_tool": "tool_executor",
        "complete": "completion"
    }
)

builder.add_edge("tool_executor", "planner")

graph = builder.compile()
```

---

# 7. Resume Capability

LangGraph allows resuming execution.

Example:

```
graph.invoke(state)
```

State loaded from PostgreSQL.

---

# 8. Failure Handling

Failures handled at node level.

Example:

```
try:

    execute_tool()

except Exception:

    persist_error()

    retry()
```

---

# 9. Execution Limits

Prevent infinite loops.

Example:

```
MAX_STEPS = 20
```

---

# 10. Timeout Controls

Example:

```
MAX_RUNTIME_SECONDS = 30
```

---

# 11. Human-in-the-Loop Integration

Completion node can trigger human review.

---

# 12. Observability Integration

Each node execution traced.

---

# 13. Scaling Model

Multiple runtime instances can run concurrently.

State consistency maintained via PostgreSQL.

---

# 14. Deployment Model

Runtime deployed as stateless service.

---

# 15. Recovery Model

Runtime can recover from crashes using persisted state.

---

# 16. Testing Strategy

Replay investigations.

Validate correctness.

---

# 17. Expected Outcome

Production-grade deterministic agent runtime.

---

# 18. Final Decision

LangGraph will be used as the production runtime engine.
