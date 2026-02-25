# ADR-003: Agent Planner and Prompt Engineering Specification

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Implementation ADR
**Related:** ADR-001, ADR-002

---

# 1. Context

The planner is the core decision-making component of the fraud investigation agent.

It determines:

- Which tool to execute
- When to terminate investigation
- How to adapt investigation dynamically

Planner must be deterministic, safe, and auditable.

---

# 2. Planner Responsibilities

Planner must:

- Analyze investigation state
- Determine next best tool
- Prevent invalid execution paths
- Ensure investigation completeness
- Terminate investigation safely

Planner must NOT:

- Execute tools directly
- Modify state outside decision scope

---

# 3. Planner Input

Planner receives:

```
InvestigationState

AvailableTools

InvestigationGoal
```

---

# 4. Planner Output

Planner returns:

```
next_action: str

reason: str

confidence: float
```

---

# 5. Planner Prompt Structure

Planner prompt template:

```
You are a fraud investigation planner.

Goal:
Investigate fraud risk for this transaction.

Current Investigation State:

Context: {context}
Similarity Results: {similarity_results}
Pattern Results: {pattern_results}
Hypotheses: {hypotheses}

Available Tools:

{tool_descriptions}

Rules:

- Do not repeat completed steps
- Ensure all required evidence is collected
- Execute tools in logical order
- Terminate only when investigation complete

Output:

Tool name only
```

---

# 6. Planner Implementation

Example:

```
def plan(state):

    prompt = build_prompt(state)

    response = llm.invoke(prompt)

    return response
```

---

# 7. Planner Safety Constraints

Planner must be constrained:

Allowed tools list

Max steps limit

Termination rules

---

# 8. Deterministic Planner Mode

Optional hybrid mode:

Rule-based planner first

LLM planner fallback

Improves safety.

---

# 9. Planner Logging

Every planner decision logged.

Ensures auditability.

---

# 10. Expected Outcome

Planner enables autonomous and adaptive investigation.

---

# 11. Future Enhancements

Self-improving planner

Planner fine-tuning

---

# 12. Final Decision

Planner will be implemented using constrained LLM prompts with safety controls.
