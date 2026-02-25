"""Prometheus metrics for Ops Agent."""

from prometheus_client import Counter, Gauge, Histogram

# ---------------------------------------------------------------------------
# Investigation - agentic execution
# ---------------------------------------------------------------------------

ops_agent_investigation_requests_total = Counter(
    "ops_agent_investigation_requests_total",
    "Total investigation requests",
    ["mode", "status"],
)

ops_agent_investigation_latency_seconds = Histogram(
    "ops_agent_investigation_latency_seconds",
    "End-to-end investigation latency in seconds",
    ["mode"],
    buckets=[0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 30.0, 60.0],
)

ops_agent_investigation_steps = Histogram(
    "ops_agent_investigation_steps",
    "Number of steps per investigation",
    ["status"],
    buckets=[1, 2, 3, 4, 5, 6, 8, 10, 15, 20],
)

ops_agent_investigation_completed_total = Counter(
    "ops_agent_investigation_completed_total",
    "Total completed investigations",
    ["status", "severity"],
)

# ---------------------------------------------------------------------------
# Planner decisions
# ---------------------------------------------------------------------------

ops_agent_planner_decisions_total = Counter(
    "ops_agent_planner_decisions_total",
    "Total planner decisions",
    ["selected_tool"],
)

# ---------------------------------------------------------------------------
# Tool execution
# ---------------------------------------------------------------------------

ops_agent_tool_execution_latency_seconds = Histogram(
    "ops_agent_tool_execution_latency_seconds",
    "Tool execution latency in seconds",
    ["tool_name", "status"],
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

ops_agent_tool_execution_total = Counter(
    "ops_agent_tool_execution_total",
    "Total tool executions",
    ["tool_name", "status"],
)

# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

ops_agent_recommendations_generated_total = Counter(
    "ops_agent_recommendations_generated_total",
    "Total recommendations generated",
    ["type", "severity"],
)

ops_agent_recommendation_queue_open = Gauge(
    "ops_agent_recommendation_queue_open",
    "Open recommendations in worklist",
)

ops_agent_rule_draft_exports_total = Counter(
    "ops_agent_rule_draft_exports_total",
    "Total rule draft exports",
    ["status"],
)

# ---------------------------------------------------------------------------
# LLM calls
# ---------------------------------------------------------------------------

ops_agent_llm_calls_total = Counter(
    "ops_agent_llm_calls_total",
    "Total LLM calls",
    ["purpose", "status"],  # purpose: planner, reasoning
)

ops_agent_llm_latency_seconds = Histogram(
    "ops_agent_llm_latency_seconds",
    "LLM call latency in seconds",
    ["purpose"],
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

ops_agent_llm_tokens_total = Counter(
    "ops_agent_llm_tokens_total",
    "Total tokens consumed in LLM calls",
    ["model", "type"],  # type: input, output
)

ops_agent_llm_cost_tokens_total = Counter(
    "ops_agent_llm_cost_tokens_total",
    "LLM token usage by model for cost tracking",
    ["model", "type"],
)

# ---------------------------------------------------------------------------
# TM API
# ---------------------------------------------------------------------------

ops_agent_tm_api_latency_seconds = Histogram(
    "ops_agent_tm_api_latency_seconds",
    "TM API call latency in seconds",
    ["endpoint"],
    buckets=[0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

ops_agent_tm_api_requests_total = Counter(
    "ops_agent_tm_api_requests_total",
    "Total TM API requests",
    ["endpoint", "status_code"],
)

# ---------------------------------------------------------------------------
# State store
# ---------------------------------------------------------------------------

ops_agent_state_store_latency_seconds = Histogram(
    "ops_agent_state_store_latency_seconds",
    "State persistence latency in seconds",
    ["operation"],  # save, load
    buckets=[0.001, 0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5],
)

# ---------------------------------------------------------------------------
# External dependencies
# ---------------------------------------------------------------------------

ops_agent_dependency_failures_total = Counter(
    "ops_agent_dependency_failures_total",
    "Total external dependency failures",
    ["dependency"],
)

ops_agent_db_query_latency_seconds = Histogram(
    "ops_agent_db_query_latency_seconds",
    "Database query latency in seconds",
    ["query_name"],
    buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0],
)

ops_agent_db_query_failures_total = Counter(
    "ops_agent_db_query_failures_total",
    "Total database query failures",
    ["query_name"],
)

ops_agent_dependency_health = Gauge(
    "ops_agent_dependency_health",
    "Dependency health status (1=healthy, 0=unhealthy)",
    ["dependency"],
)
