# TDD-002: LangGraph Agent Runtime

**Status:** Proposed
**Date:** 2026-02-19
**Author:** Fraud Platform Engineering
**Decision Type:** Technical Design Document
**Related:** ADR-001, ADR-002, ADR-003, ADR-006, TDD-001

---

## 1. Overview

Define the `InvestigationState` TypedDict, the LangGraph `StateGraph` topology, the planner node (LLM-driven tool selection with safety constraints), the tool executor node, the completion node, and the `ToolRegistry`. This is the core brain of the agentic system.

---

## 2. InvestigationState (TypedDict)

**File:** `app/agent/state.py`

The central state object passed through all graph nodes. Persisted in PostgreSQL as JSONB after every step.

```python
from typing import Any, TypedDict


class ToolExecution(TypedDict):
    """Record of a single tool execution within an investigation."""
    tool_name: str
    input_summary: dict[str, Any]
    output_summary: dict[str, Any]
    execution_time_ms: int
    status: str           # SUCCESS, FAILED, TIMED_OUT
    error_message: str | None
    timestamp: str        # ISO 8601


class PlannerDecision(TypedDict):
    """Record of a single planner decision."""
    step: int
    selected_tool: str    # Tool name or "COMPLETE"
    reason: str
    confidence: float     # 0.0 - 1.0
    timestamp: str        # ISO 8601


class InvestigationState(TypedDict):
    # ── Identity ──────────────────────────────────────────────
    investigation_id: str
    transaction_id: str

    # ── Transaction Context (populated by ContextTool) ────────
    context: dict[str, Any]

    # ── Evidence (populated by analysis tools) ────────────────
    pattern_results: dict[str, Any]
    similarity_results: dict[str, Any]
    hypotheses: list[str]
    evidence: list[dict[str, Any]]

    # ── Reasoning (populated by ReasoningTool) ────────────────
    reasoning: dict[str, Any]

    # ── Outputs (populated by Recommendation/RuleDraft tools) ─
    recommendations: list[dict[str, Any]]
    rule_draft: dict[str, Any] | None

    # ── Scoring ───────────────────────────────────────────────
    confidence_score: float
    severity: str         # CRITICAL, HIGH, MEDIUM, LOW

    # ── Execution Control ─────────────────────────────────────
    status: str           # PENDING, IN_PROGRESS, COMPLETED, FAILED, TIMED_OUT
    completed_steps: list[str]
    next_action: str      # Tool name or "COMPLETE"
    step_count: int
    max_steps: int        # Default 20
    started_at: str       # ISO 8601
    completed_at: str | None

    # ── Runtime Feature Flags (persisted for audit trace) ─────
    feature_flags: dict[str, bool]     # planner_llm_enabled, reasoning_llm_enabled,
                                       # vector_search_enabled, prompt_guard_enabled
    safeguards: dict[str, Any]         # max_steps, investigation_timeout_seconds,
                                       # tool_timeout_seconds

    # ── Audit Trail ───────────────────────────────────────────
    planner_decisions: list[PlannerDecision]
    tool_executions: list[ToolExecution]
    error: str | None
```

### 2.1 State Factory

```python
def create_initial_state(
    investigation_id: str,
    transaction_id: str,
    max_steps: int = 20,
) -> InvestigationState:
    """Create a fresh investigation state with sensible defaults."""
    return InvestigationState(
        investigation_id=investigation_id,
        transaction_id=transaction_id,
        context={},
        pattern_results={},
        similarity_results={},
        hypotheses=[],
        evidence=[],
        reasoning={},
        recommendations=[],
        rule_draft=None,
        confidence_score=0.0,
        severity="LOW",
        status="PENDING",
        completed_steps=[],
        next_action="",
        step_count=0,
        max_steps=max_steps,
        started_at=utc_now().isoformat(),
        completed_at=None,
        planner_decisions=[],
        tool_executions=[],
        error=None,
    )
```

### 2.2 Design Rules

- All fields have sensible defaults via `create_initial_state()`
- State is immutable-by-convention — nodes return new state dicts, not mutate in place
- Fully JSON-serializable — no `datetime` objects, no `UUID` objects (all strings)
- `TypedDict` (not dataclass) because LangGraph requires dict-like state

---

## 3. Graph Topology

**File:** `app/agent/graph.py`

### 3.1 Execution Flow

```
START → planner → [conditional] → tool_executor → planner → ... → completion → END
                        ↘ completion (if next_action == "COMPLETE" or step_count >= max_steps)
```

### 3.2 Node Summary

| Node | Responsibility |
|------|---------------|
| `planner` | Analyzes state, selects next tool or decides to complete |
| `tool_executor` | Executes the selected tool, updates state |
| `completion` | Finalizes investigation, persists final state, triggers audit |

### 3.3 Edge Rules

**Conditional edge from `planner`:**
- If `state["next_action"] == "COMPLETE"` → route to `completion`
- If `state["step_count"] >= state["max_steps"]` → route to `completion` (safety limit)
- Otherwise → route to `tool_executor`

**Unconditional edge:**
- `tool_executor` → `planner` (always loop back for next decision)

### 3.4 Graph Construction

```python
from langgraph.graph import StateGraph, END

def build_investigation_graph(
    registry: ToolRegistry,
    llm: BaseChatModel,
    settings: Settings,
) -> CompiledGraph:
    """Build and compile the investigation StateGraph."""

    builder = StateGraph(InvestigationState)

    # ── Nodes ──────────────────────────────────────────────
    builder.add_node("planner", make_planner_node(llm, registry, settings))
    builder.add_node("tool_executor", make_executor_node(registry))
    builder.add_node("completion", make_completion_node())

    # ── Entry Point ────────────────────────────────────────
    builder.set_entry_point("planner")

    # ── Conditional Edge: planner → tool_executor or completion
    def route_after_planner(state: InvestigationState) -> str:
        if state["next_action"] == "COMPLETE":
            return "completion"
        if state["step_count"] >= state["max_steps"]:
            return "completion"
        return "tool_executor"

    builder.add_conditional_edges(
        "planner",
        route_after_planner,
        {
            "tool_executor": "tool_executor",
            "completion": "completion",
        },
    )

    # ── Unconditional Edge: tool_executor → planner ────────
    builder.add_edge("tool_executor", "planner")

    # ── Completion → END ───────────────────────────────────
    builder.add_edge("completion", END)

    return builder.compile()
```

### 3.5 Execution Limits

| Limit | Default | Configurable Via |
|-------|---------|-----------------|
| Max steps per investigation | 20 | `LANGGRAPH_MAX_STEPS` |
| Max runtime seconds | 30 | `LANGGRAPH_MAX_RUNTIME_SECONDS` |
| Per-tool timeout | 10s | `LANGGRAPH_TOOL_TIMEOUT_SECONDS` |

Runtime timeout enforced by wrapping `graph.ainvoke()` in `asyncio.timeout()`:

```python
async with asyncio.timeout(settings.langgraph.max_runtime_seconds):
    result = await graph.ainvoke(initial_state)
```

---

## 4. Planner Node

**File:** `app/agent/planner.py`

The planner is the LLM-driven brain. It receives the full `InvestigationState` and available tools, then decides what to do next.

### 4.1 Function Signature

```python
async def planner_node(state: InvestigationState) -> InvestigationState:
    """Analyze state and select next investigation tool."""
```

### 4.2 Logic Flow

1. Build prompt from state + available tools (see `app/agent/prompts.py`)
2. Call LangChain ChatModel with structured output
3. Parse response → `(tool_name: str, reason: str, confidence: float)`
4. Validate `tool_name` against registered tools
5. Check termination conditions:
   - All required evidence collected AND reasoning complete → `COMPLETE`
   - Step count >= max_steps → `COMPLETE` (with warning)
   - No more useful tools to run → `COMPLETE`
6. Append `PlannerDecision` to `state["planner_decisions"]`
7. Set `state["next_action"]` and increment `step_count`
8. Return updated state

### 4.3 Safety Constraints

Enforced in prompt AND validated in code post-LLM:

| Constraint | Enforcement |
|-----------|-------------|
| Cannot select a tool already in `completed_steps` | Code validation |
| Must select `context_tool` first if `context` is empty | Prompt rule + code validation |
| Cannot select `recommendation_tool` before analysis tools | Prompt rule |
| Cannot select `rule_draft_tool` before `recommendation_tool` | Prompt rule |
| Tool name must be in registry | Code validation (reject + fallback) |
| Max steps must not be exceeded | `route_after_planner()` check |

### 4.4 Hybrid Fallback

If LLM call fails (timeout, error, invalid response), the planner falls back to a deterministic rule-based sequence:

```python
FALLBACK_SEQUENCE = [
    "context_tool",
    "pattern_tool",
    "similarity_tool",
    "reasoning_tool",
    "recommendation_tool",
    "rule_draft_tool",
]

def _deterministic_fallback(state: InvestigationState) -> str:
    """Select next tool based on fixed ordering when LLM fails."""
    for tool_name in FALLBACK_SEQUENCE:
        if tool_name not in state["completed_steps"]:
            return tool_name
    return "COMPLETE"
```

### 4.5 Planner Decision Logging

Every decision is appended to `state["planner_decisions"]`:

```python
decision = PlannerDecision(
    step=state["step_count"] + 1,
    selected_tool=tool_name,
    reason=reason,
    confidence=confidence,
    timestamp=utc_now().isoformat(),
)
state["planner_decisions"].append(decision)
```

---

## 5. Planner Prompt

**File:** `app/agent/prompts.py`

```python
PLANNER_SYSTEM_PROMPT = """\
You are a fraud investigation planner for a card fraud operations team.
Your job is to determine the NEXT investigation step based on current evidence.

You must respond with a JSON object: {"tool": "<name>", "reason": "<why>", "confidence": <0.0-1.0>}
Or to finish: {"tool": "COMPLETE", "reason": "<why>", "confidence": <0.0-1.0>}
"""

PLANNER_USER_TEMPLATE = """\
## Current Investigation State

Transaction ID: {transaction_id}
Completed Steps: {completed_steps}
Step Count: {step_count} / {max_steps}

### Evidence Collected
- Context Available: {has_context}
- Pattern Analysis Done: {has_patterns}
- Similarity Analysis Done: {has_similarity}
- Reasoning Done: {has_reasoning}
- Recommendations Generated: {has_recommendations}
- Rule Draft Generated: {has_rule_draft}
- Current Confidence: {confidence_score}
- Current Severity: {severity}

### Key Findings So Far
{findings_summary}

## Available Tools
{tool_descriptions}

## Rules
1. ALWAYS retrieve context first if not yet available.
2. Run analysis tools (pattern_tool, similarity_tool) BEFORE reasoning_tool.
3. Run reasoning_tool BEFORE recommendation_tool.
4. Run rule_draft_tool ONLY AFTER recommendation_tool.
5. NEVER repeat a tool that is already in completed_steps.
6. Output COMPLETE when the investigation has sufficient evidence and recommendations.
7. Consider confidence and severity when deciding whether more analysis is needed.

## Decision
Select the next tool to execute, or COMPLETE if the investigation is sufficient.
"""
```

---

## 6. Tool Executor Node

**File:** `app/agent/executor.py`

### 6.1 Function Signature

```python
async def tool_executor_node(state: InvestigationState) -> InvestigationState:
    """Execute the selected tool and update state."""
```

### 6.2 Logic Flow

1. Get tool from registry by `state["next_action"]`
2. Start OTel span `tool.{tool_name}`
3. Record start time via `perf_counter()`
4. Execute `await tool.execute(state)` with per-tool timeout (default 10s)
5. Record end time, compute `execution_time_ms`
6. Append `ToolExecution` record to `state["tool_executions"]`
7. Append tool name to `state["completed_steps"]`
8. Return updated state

### 6.3 Error Handling

Tool failures are **non-fatal**. The planner will adapt:

```python
try:
    async with asyncio.timeout(tool_timeout_seconds):
        updated_state = await tool.execute(state)
except asyncio.TimeoutError:
    execution = ToolExecution(
        tool_name=tool_name,
        status="TIMED_OUT",
        error_message=f"Tool timed out after {tool_timeout_seconds}s",
        ...
    )
    # Tool marked as completed (to prevent retry loops)
    # Planner will decide next action without this tool's results
except Exception as exc:
    execution = ToolExecution(
        tool_name=tool_name,
        status="FAILED",
        error_message=str(exc),
        ...
    )
    # Same: mark completed, planner adapts
```

---

## 7. Completion Node

**File:** `app/agent/completion.py`

### 7.1 Function Signature

```python
async def completion_node(state: InvestigationState) -> InvestigationState:
    """Finalize investigation and persist results."""
```

### 7.2 Logic Flow

1. Set `state["status"] = "COMPLETED"`
2. Set `state["completed_at"] = utc_now().isoformat()`
3. Compute final `confidence_score` from evidence + reasoning
4. Determine final `severity` from pattern + similarity + reasoning results
5. Persist investigation state to `ops_agent_investigation_state` table
6. Persist tool execution log entries to `ops_agent_tool_execution_log`
7. Persist insights + evidence via `insight_repository`
8. Persist recommendations via `recommendation_repository`
9. Write audit log entry
10. Emit Prometheus metrics (`investigation_completed`, latency, step_count)
11. Return final state

### 7.3 Persistence Order

```
1. investigation_repository.complete(...)     # Update status, severity, confidence
2. state_store.save_state(...)                # Final JSONB snapshot
3. tool_log_repository.log_executions(...)    # Batch insert tool logs
4. insight_repository.upsert_insight(...)     # Evidence-derived insights
5. recommendation_repository.upsert(...)      # Recommendations
6. audit_repository.append(...)               # Audit trail
```

---

## 8. Tool Registry

**File:** `app/agent/registry.py`

Simple dict-based registry. Tools register at graph build time.

```python
from app.tools.base import BaseTool


class ToolRegistry:
    """Registry for investigation tools."""

    def __init__(self) -> None:
        self._tools: dict[str, BaseTool] = {}

    def register(self, tool: BaseTool) -> None:
        """Register a tool by its name."""
        if tool.name in self._tools:
            raise ValueError(f"Tool already registered: {tool.name}")
        self._tools[tool.name] = tool

    def get(self, name: str) -> BaseTool:
        """Get a tool by name. Raises KeyError if not found."""
        if name not in self._tools:
            raise KeyError(f"Unknown tool: {name}")
        return self._tools[name]

    def list_tools(self) -> list[dict[str, str]]:
        """List all registered tools with name and description."""
        return [
            {"name": t.name, "description": t.description}
            for t in self._tools.values()
        ]

    def has(self, name: str) -> bool:
        """Check if a tool is registered."""
        return name in self._tools

    @property
    def tool_names(self) -> list[str]:
        """Return sorted list of registered tool names."""
        return sorted(self._tools.keys())
```

### 8.1 Registration (in `build_investigation_graph`)

```python
registry = ToolRegistry()
registry.register(ContextTool(tm_client=tm_client))
registry.register(PatternTool())
registry.register(SimilarityTool(embedding_client=embedding_client, session=session))
registry.register(ReasoningTool(llm=llm))
registry.register(RecommendationTool())
registry.register(RuleDraftTool())
```

---

## 9. Configuration Additions

Add to `app/core/config.py`:

```python
class LangGraphConfig(BaseSettings):
    """LangGraph runtime configuration."""
    model_config = SettingsConfigDict(env_prefix="LANGGRAPH_")

    max_steps: int = 20
    investigation_timeout_seconds: int = 120    # Total investigation timeout
    tool_timeout_seconds: int = 30              # Per-tool timeout
    enable_planner_fallback: bool = True


class PlannerConfig(BaseSettings):
    """Planner LLM configuration."""
    model_config = SettingsConfigDict(env_prefix="PLANNER_")

    llm_enabled: bool = True                    # False = pure deterministic fallback
    model_name: str = "ollama/llama3.2"         # Local-first, overridable
    temperature: float = 0.1                    # Low temp for consistent tool selection
    max_tokens: int = 256
    timeout_seconds: int = 10                   # Per-planner-call timeout
    prompt_guard_enabled: bool = True           # Input sanitization (TDD-008 §4)
    fallback_sequence: list[str] = [
        "context_tool",
        "pattern_tool",
        "similarity_tool",
        "reasoning_tool",
        "recommendation_tool",
        "rule_draft_tool",
    ]
```

Add to root `Settings` class:

```python
class Settings(BaseSettings):
    # ... existing fields ...
    langgraph: LangGraphConfig = LangGraphConfig()
    planner: PlannerConfig = PlannerConfig()
```

---

## 10. Graph Invocation Pattern

How the service layer invokes the graph:

```python
async def run_investigation(
    self,
    transaction_id: str,
    mode: str = "FULL",
) -> InvestigationState:
    """Run a complete fraud investigation."""
    investigation_id = str(uuid.uuid7())

    # 1. Create investigation record in DB
    await self._investigation_repo.create(
        investigation_id=investigation_id,
        transaction_id=transaction_id,
        mode=mode,
    )

    # 2. Build graph
    graph = build_investigation_graph(
        registry=self._registry,
        llm=self._llm,
        settings=self._settings,
    )

    # 3. Create initial state
    initial_state = create_initial_state(
        investigation_id=investigation_id,
        transaction_id=transaction_id,
        max_steps=self._settings.langgraph.max_steps,
    )

    # 4. Invoke with timeout
    try:
        async with asyncio.timeout(self._settings.langgraph.max_runtime_seconds):
            result = await graph.ainvoke(initial_state)
    except asyncio.TimeoutError:
        result = {**initial_state, "status": "TIMED_OUT"}

    return result
```

---

## 11. Resume Capability

If system crashes mid-investigation, state can be loaded from PostgreSQL and re-invoked:

```python
async def resume_investigation(self, investigation_id: str) -> InvestigationState:
    """Resume a failed or interrupted investigation."""
    stored_state = await self._state_store.load_state(investigation_id)
    if stored_state is None:
        raise NotFoundError(f"No state found for investigation {investigation_id}")

    graph = build_investigation_graph(...)
    result = await graph.ainvoke(stored_state)
    return result
```

This works because LangGraph's `StateGraph.ainvoke()` accepts any valid state dict and continues from wherever that state left off — the planner node evaluates `completed_steps` to determine what remains.

---

## 12. Observability Integration

Each node is traced with OpenTelemetry:

```python
from opentelemetry import trace

tracer = trace.get_tracer("fraud-agent")

async def planner_node(state):
    with tracer.start_as_current_span("agent.planner") as span:
        span.set_attribute("investigation_id", state["investigation_id"])
        span.set_attribute("step_count", state["step_count"])
        # ... planner logic ...
        span.set_attribute("selected_tool", state["next_action"])

async def tool_executor_node(state):
    with tracer.start_as_current_span(f"agent.tool.{state['next_action']}") as span:
        span.set_attribute("investigation_id", state["investigation_id"])
        # ... execution logic ...
        span.set_attribute("execution_time_ms", execution_time_ms)
```

Prometheus metrics emitted:
- `ops_agent_planner_decisions_total` (Counter, labels: selected_tool, used_fallback)
- `ops_agent_tool_execution_latency_seconds` (Histogram, labels: tool_name, status)
- `ops_agent_investigation_steps` (Histogram, buckets: 1-20)
- `ops_agent_investigation_completed_total` (Counter, labels: status, severity)
