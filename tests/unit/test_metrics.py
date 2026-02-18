"""Unit tests for metrics module."""

from app.core import metrics


def test_metrics_are_defined():
    assert hasattr(metrics, "ops_agent_investigation_requests_total")
    assert hasattr(metrics, "ops_agent_investigation_latency_seconds")
    assert hasattr(metrics, "ops_agent_pipeline_stage_latency_seconds")
    assert hasattr(metrics, "ops_agent_recommendations_generated_total")
    assert hasattr(metrics, "ops_agent_recommendation_queue_open")
    assert hasattr(metrics, "ops_agent_rule_draft_exports_total")
    assert hasattr(metrics, "ops_agent_llm_calls_total")
    assert hasattr(metrics, "ops_agent_llm_latency_seconds")
    assert hasattr(metrics, "ops_agent_llm_tokens_total")
    assert hasattr(metrics, "ops_agent_dependency_failures_total")
    assert hasattr(metrics, "ops_agent_db_query_latency_seconds")
    assert hasattr(metrics, "ops_agent_db_query_failures_total")


def test_metrics_have_labels():
    # These are Counter/Histogram instances
    assert hasattr(metrics.ops_agent_investigation_requests_total, "labels")
    assert hasattr(metrics.ops_agent_investigation_latency_seconds, "labels")
    assert hasattr(metrics.ops_agent_pipeline_stage_latency_seconds, "labels")
    assert hasattr(metrics.ops_agent_recommendations_generated_total, "labels")
    assert hasattr(metrics.ops_agent_db_query_latency_seconds, "labels")
