"""Prometheus metrics for Ops Agent."""

from prometheus_client import Counter, Histogram

# ---------------------------------------------------------------------------
# Investigation pipeline — end-to-end
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
    buckets=[0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 30.0],
)

# ---------------------------------------------------------------------------
# Per-stage pipeline latency
# ---------------------------------------------------------------------------

ops_agent_pipeline_stage_latency_seconds = Histogram(
    "ops_agent_pipeline_stage_latency_seconds",
    "Latency per pipeline stage in seconds",
    ["stage"],  # context_build | pattern_analysis | similarity | llm_reasoning | recommendations
    buckets=[0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.0, 5.0],
)

# ---------------------------------------------------------------------------
# Recommendations
# ---------------------------------------------------------------------------

ops_agent_recommendations_generated_total = Counter(
    "ops_agent_recommendations_generated_total",
    "Total recommendations generated",
    ["type", "severity"],
)

ops_agent_recommendation_queue_open = Counter(
    "ops_agent_recommendation_queue_open",
    "Open recommendations in worklist",
)

ops_agent_rule_draft_exports_total = Counter(
    "ops_agent_rule_draft_exports_total",
    "Total rule draft exports",
    ["status"],
)

# ---------------------------------------------------------------------------
# LLM / hybrid mode
# ---------------------------------------------------------------------------

ops_agent_llm_calls_total = Counter(
    "ops_agent_llm_calls_total",
    "Total LLM calls",
    ["status"],  # success | fallback | error
)

ops_agent_llm_latency_seconds = Histogram(
    "ops_agent_llm_latency_seconds",
    "LLM call latency in seconds",
    buckets=[0.5, 1.0, 2.0, 3.0, 5.0, 10.0, 30.0],
)

ops_agent_llm_consistency_score = Histogram(
    "ops_agent_llm_consistency_score",
    "LLM consistency check scores (0.0–1.0)",
    buckets=[0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 1.0],
)

ops_agent_llm_tokens_total = Counter(
    "ops_agent_llm_tokens_total",
    "Total tokens consumed in LLM calls",
    ["type"],  # prompt | completion
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
