# Agentic Runtime Specification

This is the canonical implementation spec for the current LangGraph runtime.
It replaces legacy detail ADRs (`adr_002` to `adr_008`).

## Scope

- Runtime orchestration and tool execution model
- Planner and fallback behavior
- Investigation state, memory, and evidence outputs
- Safety, governance, and observability boundaries

## Execution Model

- Entry node: `planner_node`
- Loop: `planner_node -> executor_node -> planner_node`
- Exit node: `completion_node`
- Investigation stops when planner selects `COMPLETE` or max-step/timeout limits are hit.

## Planner Behavior

- Primary path: LLM planner selects next tool from registry.
- Guardrails:
  - only valid tools can be selected;
  - completed tools are not repeated;
  - rule-sequence fallback is used on planner failure/circuit-open/invalid decision.
- Planner decision records are persisted in investigation state.

## Tool Contract

All tools operate on shared `InvestigationState` and return updated state.

Active toolset:

- `context_tool`
- `pattern_tool`
- `similarity_tool`
- `reasoning_tool`
- `recommendation_tool`
- `rule_draft_tool`

Each tool execution records:

- `tool_name`
- `status`
- `input_summary`
- `output_summary`
- `execution_time_ms`
- `error_message` (if any)

## State and Memory Model

- Working memory: persisted investigation state (`context`, evidence, tool outputs, reasoning, recommendations, rule draft).
- Historical memory: prior investigations and insights in `ops_agent_*` tables.
- Vector memory: similarity retrieval backed by transaction embeddings (`ops_agent_transaction_embeddings` + pgvector queries).

## Similarity and Embedding Path

- Embeddings use configured provider/model (`mxbai-embed-large`, 1024 dim expected in current config).
- Similarity search is thresholded and bounded (`search_limit`, `min_similarity`).
- On embedding/vector failure, heuristic SQL fallback runs and diagnostics are attached to `similarity_results.vector_diagnostics`.

## LLM Usage in Flow

LLM is used in two stages:

1. Planner stage (`planner_node`) for next-tool selection.
2. Reasoning stage (`reasoning_tool`) for structured risk synthesis.

If reasoning LLM fails/times out/parses poorly, the tool emits evidence-based fallback reasoning instead of failing the whole investigation.

## Safety and Governance

- Final fraud disposition is human-controlled.
- Rule activation is human-controlled (maker-checker flow in Rule Management).
- Redaction/pseudonym policy applies to LLM payloads.
- Bounded autonomy via max steps, node/tool timeouts, and fallback sequencing.

## Observability and Evidence Trail

- OpenTelemetry spans for planner/tool stages.
- Prometheus metrics for tool latency/status and LLM calls/tokens/latency.
- Investigation API returns full stage trace (`planner_decisions`, `tool_executions`) plus evidence artifacts.
- E2E reports show per-stage request/response and KPI gate outcomes.

## Failure Handling

- Planner errors: fallback sequence path.
- Tool timeout/error: recorded in `tool_executions`, investigation continues where possible.
- Similarity failure: heuristic fallback + diagnostics.
- Reasoning failure: evidence fallback payload with `llm_status` marker.
- State persistence supports replay and audit.

## Non-Goals

- Autonomous final fraud decisions.
- Autonomous rule activation.
- Unbounded tool execution without guardrails.
