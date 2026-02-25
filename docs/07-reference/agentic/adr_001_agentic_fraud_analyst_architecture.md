# ADR-001: Migration to True Agentic Architecture for Card Fraud Ops Analyst Agent

**Status:** Accepted\
**Date:** 2026-02-19\
**Implemented:** 2026-02-23\
**Author:** Fraud Platform Engineering\
**Decision Type:** Architectural Decision Record (ADR)

---

# 1. Context

At the time this ADR was authored (2026-02-19), the Card Fraud Ops Analyst Agent was a deterministic multi-stage pipeline consisting of:

- context\_builder
- pattern\_engine
- similarity\_engine
- reasoning\_engine
- recommendation\_engine
- rule\_draft\_engine
- audit\_engine

That pipeline provided structured fraud investigation assistance using LLM reasoning and deterministic fraud analysis tools.

However, the system at that time was **not a true autonomous agentic system**, because:

- Execution flow is static and pre-defined
- No dynamic planning capability
- No autonomous tool selection
- No execution loop
- No persistent investigation state
- No adaptive reasoning

This limited the system's ability to:

- Adapt investigation based on intermediate findings
- Dynamically select relevant analysis tools
- Improve investigation quality autonomously
- Scale investigation complexity without code changes

Fraud investigation is inherently stateful, non-linear, and evidence-driven. Therefore, an agentic architecture was required.

This migration is now complete. The production runtime uses LangGraph with planner, executor, completion, and tool nodes with persisted state and full tool I/O audit trails.

---

# 2. Problem Statement

The prior pipeline architecture could not support:

- Autonomous investigation planning
- Dynamic tool orchestration
- Iterative reasoning
- Adaptive evidence gathering
- Persistent investigation memory
- Controlled autonomous execution

This prevented the system from evolving into a fully autonomous fraud investigation agent.

---

# 3. Decision

This ADR approved migration from the deterministic pipeline to a **stateful agentic architecture using LangGraph as the orchestration engine**.

The implemented architecture introduced:

- Planner
- Tool abstraction layer
- Stateful investigation memory
- Execution loop
- Graph-based orchestration
- Deterministic autonomy with bounded execution

LangGraph is the orchestration runtime.

LangSmith is not used. Observability is implemented using OpenTelemetry and PostgreSQL.

---

# 4. Goals

## Primary Goals

Enable autonomous fraud investigation with:

- Dynamic investigation planning
- Autonomous tool selection
- Stateful investigation execution
- Iterative reasoning
- Auditability and explainability

## Secondary Goals

Maintain:

- Deterministic execution
- Compliance and audit safety
- Human-in-the-loop approval
- Observability
- Replayability

---

# 5. Non-Goals

The following are explicitly NOT goals:

- Fully uncontrolled autonomous rule deployment
- Removal of human approval
- Non-deterministic execution
- Experimental multi-agent chaos

Safety and auditability remain primary constraints.

---

# 6. Architecture Overview

## Architecture at ADR Time

Linear pipeline:

context -> similarity -> pattern -> reasoning -> recommendation -> rule draft

## Implemented Architecture

Stateful agent graph:

Planner -> Tool -> State Update -> Planner -> Tool -> State Update -> Recommendation

Graph-based execution has replaced the static pipeline.

---

# 7. Core Architecture Components

## 7.1 Investigation State

Central state object persisted across execution.

Example:

```python
class InvestigationState:

    investigation_id: str

    transaction_id: str

    context: dict

    evidence: list

    similarity_results: list

    pattern_results: list

    hypotheses: list

    recommendations: list

    rule_draft: dict

    confidence_score: float

    completed_steps: list

    next_steps: list

    status: str
```

State stored in PostgreSQL.

---

## 7.2 Tool Layer

Existing engines will be converted into tools.

Example tools:

- ContextTool
- SimilarityTool
- PatternTool
- ReasoningTool
- RecommendationTool
- RuleDraftTool

Tool interface:

```python
class Tool:

    name: str

    description: str

    def execute(self, state: InvestigationState) -> InvestigationState:
        pass
```

Tools remain deterministic.

---

## 7.3 Planner

Planner is an LLM-driven component that determines next action.

Planner input:

- current investigation state
- available tools
- investigation goal

Planner output:

- next tool to execute
- termination decision

Planner prompt defines investigation policy.

---

## 7.4 Executor

Executor runs investigation loop.

Pseudo-code:

```python
while state.status != "COMPLETED":

    next_tool = planner.plan(state)

    tool = tool_registry.get(next_tool)

    state = tool.execute(state)

    persist(state)
```

Executor ensures deterministic execution.

---

## 7.5 LangGraph Orchestration Layer

LangGraph manages:

- State transitions
- Execution graph
- Tool invocation
- Planner integration
- Persistence hooks

LangGraph provides deterministic graph execution.

---

# 8. Storage Architecture

PostgreSQL will store:

Tables:

investigations\
investigation\_state\
tool\_execution\_log\
recommendations\
audit\_log

This ensures:

- Auditability
- Replayability
- Compliance

---

# 9. Observability

OpenTelemetry will capture:

- Tool execution time
- Planner decisions
- State transitions
- Errors

Jaeger will visualize traces.

Grafana will monitor metrics.

LangSmith is not used.

---

# 10. Execution Flow

1. Investigation request received

2. Investigation state initialized

3. Planner determines first tool

4. Tool executes

5. State updated

6. Planner determines next tool

7. Loop continues

8. Recommendation generated

9. Rule draft generated

10. Human review required

11. Investigation marked complete

---

# 11. Migration Plan

## Phase 1: Tool Refactoring

Convert engines into tools.

Estimated effort: 2 days

---

## Phase 2: State Model Implementation

Implement InvestigationState model.

Estimated effort: 1 day

---

## Phase 3: Planner Implementation

Implement LLM planner.

Estimated effort: 2 days

---

## Phase 4: LangGraph Integration

Implement execution graph.

Estimated effort: 2 days

---

## Phase 5: Persistence Layer

Implement PostgreSQL state persistence.

Estimated effort: 2 days

---

## Phase 6: Observability

Integrate OpenTelemetry.

Estimated effort: 2 days

---

## Phase 7: Testing

Functional testing Replay testing Load testing

Estimated effort: 5 days

---

Total Estimated Effort: 2-3 weeks

---

# 12. Alternatives Considered

## Option 1: Phidata

Rejected because:

- Less deterministic
- Limited orchestration control
- Less suitable for regulated environments

## Option 2: AutoGen

Rejected because:

- Non-deterministic
- Hard to control execution
- Experimental

## Option 3: Custom Orchestrator

Rejected because:

- Reinvents LangGraph
- Higher engineering effort

---

# 13. Consequences

## Positive

- True agentic architecture
- Autonomous investigation
- Improved fraud detection
- Better scalability

## Negative

- Increased architectural complexity
- Additional infrastructure requirements

---

# 14. Risks

Risk: Planner makes incorrect decisions\
Mitigation: constrained tool selection

Risk: Increased latency\
Mitigation: planner optimization

Risk: State corruption\
Mitigation: transactional persistence

---

# 15. Success Metrics

- Investigation accuracy improvement
- Reduced manual analyst workload
- Faster investigation time
- High audit traceability

---

# 16. Future Enhancements

- Multi-agent collaboration
- Continuous learning
- Autonomous pattern discovery

---

# 17. Final Decision

Migration to a LangGraph-based stateful agentic architecture has been completed while maintaining deterministic execution, auditability, and human oversight.

---

# 18. Repository Structure (Target at ADR Authoring Time)

The following production-ready repository structure is recommended:

```
fraud-agent/

  agent/
    graph.py
    planner.py
    executor.py
    state.py
    registry.py

  tools/
    context_tool.py
    similarity_tool.py
    pattern_tool.py
    reasoning_tool.py
    recommendation_tool.py
    rule_draft_tool.py

  memory/
    postgres_store.py
    models.py

  api/
    investigation_api.py

  observability/
    tracing.py
    metrics.py

  config/
    settings.py

  tests/
    test_agent.py
    test_tools.py
```

This structure separates:

- agent runtime
- tools
- persistence
- API layer
- observability

---

# 19. LangGraph Implementation Skeleton

## 19.1 Investigation State

```
from typing import TypedDict, List, Dict

class InvestigationState(TypedDict):

    investigation_id: str

    transaction_id: str

    context: Dict

    evidence: List[Dict]

    similarity_results: List[Dict]

    pattern_results: List[Dict]

    hypotheses: List[str]

    recommendations: List[Dict]

    rule_draft: Dict

    confidence_score: float

    next_action: str

    status: str
```

---

## 19.2 Tool Registry

```
class ToolRegistry:

    def __init__(self):
        self.tools = {}

    def register(self, tool):
        self.tools[tool.name] = tool

    def get(self, name):
        return self.tools[name]
```

---

## 19.3 Planner

```
def planner_node(state: InvestigationState) -> InvestigationState:

    prompt = build_planner_prompt(state)

    decision = llm.invoke(prompt)

    state["next_action"] = decision

    return state
```

---

## 19.4 Tool Execution Node

```
def tool_node(state: InvestigationState):

    tool = registry.get(state["next_action"])

    updated_state = tool.execute(state)

    return updated_state
```

---

## 19.5 LangGraph Graph

```
from langgraph.graph import StateGraph

builder = StateGraph(InvestigationState)

builder.add_node("planner", planner_node)

builder.add_node("tool", tool_node)

builder.set_entry_point("planner")

builder.add_edge("planner", "tool")

builder.add_edge("tool", "planner")

builder.set_finish_point("complete")

graph = builder.compile()
```

---

# 20. Planner Prompt Design (Fraud-Specific)

Planner prompt determines agent intelligence.

Example:

```
You are a fraud investigation agent.

Goal:
Investigate fraud risk for the transaction.

Current State:

Context: {context}
Similarity Results: {similarity_results}
Pattern Results: {pattern_results}

Available Tools:

- context_tool
- similarity_tool
- pattern_tool
- reasoning_tool
- recommendation_tool
- rule_draft_tool

Determine the next best action.

Rules:

- Always retrieve context first
- Use similarity tool if similarity results missing
- Use pattern tool if pattern analysis missing
- Use reasoning tool after evidence collection
- Use recommendation tool after reasoning
- Use rule draft tool last

Output only tool name.
```

---

# 21. PostgreSQL Schema

(See ADR-002-Agentic-Fraud-Analyst-Implementation-Details for complete schema, persistence strategy, observability, migration rollout, and future multi-agent extensions.)

This ADR focuses on architectural decision and high-level orchestration design only.

---

# 22. Document Split Strategy

Due to document size constraints, implementation-heavy details are moved to a separate ADR:

**ADR-001 (this document):**

- Architecture decision
- Agent model
- Planner design
- Tool abstraction
- LangGraph orchestration model
- Repository structure

**ADR-002 (new document):**

- Full PostgreSQL schema
- Persistence implementation
- Tool execution logging
- Observability implementation
- Migration rollout plan
- Production hardening
- Multi-agent roadmap

This separation improves maintainability and clarity.

---

# 23. Final Outcome

Result is a true autonomous fraud investigation agent with:

- Dynamic planning
- Stateful execution
- Autonomous tool orchestration
- Full auditability
- Production safety
