"""Tool executor node - executes selected tools with timeout handling."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING, Any

import structlog
from opentelemetry import trace

from app.agent.state import InvestigationState, ToolExecution
from app.core.config import get_settings
from app.core.metrics import (
    ops_agent_tool_execution_latency_seconds,
    ops_agent_tool_execution_total,
)
from app.utils.clock import utc_now
from app.utils.redaction import redact_card_id

if TYPE_CHECKING:
    from app.agent.registry import ToolRegistry

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _value_from_mapping_or_obj(value: Any, key: str) -> Any:
    if isinstance(value, dict):
        return value.get(key)
    return getattr(value, key, None)


def _signal_names(context: dict[str, Any]) -> list[str]:
    names: list[str] = []
    for signal in _as_list(context.get("signals")):
        if isinstance(signal, dict):
            name = signal.get("name")
        else:
            name = getattr(signal, "name", None)
        if isinstance(name, str) and name:
            names.append(name)
    return names[:8]


def _window_counts(context: dict[str, Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    windows = _as_dict(context.get("windows"))
    for key, window in windows.items():
        count = 0
        if isinstance(window, dict):
            raw = window.get("transaction_count", 0)
            if isinstance(raw, (int, float)):
                count = int(raw)
        else:
            raw = getattr(window, "transaction_count", 0)
            if isinstance(raw, (int, float)):
                count = int(raw)
        counts[str(key)] = count
    return counts


def _summarize_context(context_raw: Any) -> dict[str, Any]:
    context = _as_dict(context_raw)
    transaction = context.get("transaction")
    card_id = _value_from_mapping_or_obj(transaction, "card_id")
    redacted_card_id = redact_card_id(card_id) if isinstance(card_id, str) else None
    return {
        "transaction_id": _value_from_mapping_or_obj(transaction, "transaction_id"),
        "amount": _value_from_mapping_or_obj(transaction, "amount"),
        "currency": _value_from_mapping_or_obj(transaction, "currency"),
        "decision": (
            _value_from_mapping_or_obj(transaction, "decision")
            or _value_from_mapping_or_obj(transaction, "status")
        ),
        "card_id": redacted_card_id,
        "merchant_id": _value_from_mapping_or_obj(transaction, "merchant_id"),
        "window_counts": _window_counts(context),
        "signal_names": _signal_names(context),
        "rule_match_count": len(_as_list(context.get("rule_matches"))),
        "card_history_count": len(_as_list(context.get("card_history"))),
    }


def _summarize_pattern_results(pattern_results_raw: Any) -> dict[str, Any]:
    pattern_results = _as_dict(pattern_results_raw)
    scores = [
        item
        for item in _as_list(pattern_results.get("scores"))
        if isinstance(item, dict) and isinstance(item.get("pattern_name"), str)
    ]

    def _score_value(item: dict[str, Any]) -> float:
        try:
            return float(item.get("score", 0.0) or 0.0)
        except TypeError, ValueError:
            return 0.0

    top_scores = sorted(scores, key=_score_value, reverse=True)[:3]
    return {
        "overall_score": float(pattern_results.get("overall_score", 0.0) or 0.0),
        "patterns_detected": [
            str(item) for item in _as_list(pattern_results.get("patterns_detected"))
        ],
        "top_scores": [
            {
                "pattern_name": item.get("pattern_name"),
                "score": _score_value(item),
            }
            for item in top_scores
        ],
    }


def _summarize_similarity_results(similarity_results_raw: Any) -> dict[str, Any]:
    similarity_results = _as_dict(similarity_results_raw)
    matches = [
        item for item in _as_list(similarity_results.get("matches")) if isinstance(item, dict)
    ]
    summary: dict[str, Any] = {
        "overall_score": float(similarity_results.get("overall_score", 0.0) or 0.0),
        "match_count": len(matches),
        "match_types": [str(item.get("match_type", "unknown")) for item in matches[:5]],
        "has_counter_evidence": bool(similarity_results.get("counter_evidence")),
    }
    if "skipped" in similarity_results:
        summary["skipped"] = bool(similarity_results.get("skipped"))

    vector_diagnostics = _as_dict(similarity_results.get("vector_diagnostics"))
    if vector_diagnostics:
        candidate_count_raw = vector_diagnostics.get("candidate_count", 0)
        search_limit_raw = vector_diagnostics.get("search_limit", 0)
        min_similarity_raw = vector_diagnostics.get("min_similarity", 0.0)
        embedding_dimension_raw = vector_diagnostics.get("embedding_dimension", 0)
        try:
            candidate_count = int(candidate_count_raw or 0)
        except TypeError, ValueError:
            candidate_count = 0
        try:
            search_limit = int(search_limit_raw or 0)
        except TypeError, ValueError:
            search_limit = 0
        try:
            min_similarity = float(min_similarity_raw or 0.0)
        except TypeError, ValueError:
            min_similarity = 0.0
        try:
            embedding_dimension = int(embedding_dimension_raw or 0)
        except TypeError, ValueError:
            embedding_dimension = 0

        summary["vector_diagnostics"] = {
            "candidate_count": candidate_count,
            "search_limit": search_limit,
            "min_similarity": min_similarity,
            "embedding_model": vector_diagnostics.get("embedding_model"),
            "embedding_dimension": embedding_dimension,
            "reason": vector_diagnostics.get("reason"),
        }
    return summary


def _summarize_reasoning(reasoning_raw: Any) -> dict[str, Any]:
    reasoning = _as_dict(reasoning_raw)
    findings = _as_list(reasoning.get("key_findings"))
    return {
        "llm_status": reasoning.get("llm_status"),
        "risk_level": reasoning.get("risk_level"),
        "severity": reasoning.get("severity"),
        "confidence": reasoning.get("confidence"),
        "summary": (reasoning.get("summary") or reasoning.get("narrative") or "")[:240],
        "findings_count": len(findings),
    }


def _summarize_recommendations(recommendations_raw: Any) -> dict[str, Any]:
    recommendations = [item for item in _as_list(recommendations_raw) if isinstance(item, dict)]
    rec_types = [
        str(item.get("type") or item.get("recommendation_type") or "") for item in recommendations
    ]
    return {
        "count": len(recommendations),
        "types": rec_types[:8],
    }


def _summarize_rule_draft(rule_draft_raw: Any) -> dict[str, Any]:
    rule_draft = _as_dict(rule_draft_raw)
    return {
        "has_rule_draft": bool(rule_draft),
        "rule_name": rule_draft.get("rule_name"),
        "condition_count": len(_as_list(rule_draft.get("conditions"))),
    }


def _build_input_summary(state: InvestigationState, tool_name: str) -> dict[str, Any]:
    summary: dict[str, Any] = {
        "transaction_id": state.get("transaction_id"),
        "current_severity": state.get("severity"),
        "step_count": state.get("step_count", 0),
        "completed_steps": list(state.get("completed_steps", [])),
    }
    if tool_name in {"pattern_tool", "similarity_tool", "reasoning_tool", "recommendation_tool"}:
        summary["context"] = _summarize_context(state.get("context"))
    if tool_name in {"similarity_tool", "reasoning_tool", "recommendation_tool"}:
        summary["pattern_results"] = _summarize_pattern_results(state.get("pattern_results"))
    if tool_name in {"reasoning_tool", "recommendation_tool"}:
        summary["similarity_results"] = _summarize_similarity_results(
            state.get("similarity_results")
        )
    if tool_name == "recommendation_tool":
        summary["reasoning"] = _summarize_reasoning(state.get("reasoning"))
    if tool_name == "rule_draft_tool":
        summary["recommendations"] = _summarize_recommendations(state.get("recommendations"))
    return summary


def _build_output_summary(
    state: InvestigationState,
    tool_name: str,
    *,
    status: str,
    error_message: str | None = None,
) -> dict[str, Any]:
    normalized_status = str(status).strip().upper() or "UNKNOWN"
    llm_status = normalized_status.lower()
    summary: dict[str, Any] = {
        "status": normalized_status,
        "severity": state.get("severity"),
    }
    if error_message:
        summary["error_message"] = error_message[:240]
        if tool_name == "reasoning_tool":
            summary["reasoning"] = {
                "llm_status": llm_status,
                "summary": "Reasoning tool did not produce usable output.",
            }
        return summary
    if normalized_status != "SUCCESS":
        if tool_name == "reasoning_tool":
            summary["reasoning"] = {
                "llm_status": llm_status,
                "summary": "Reasoning tool did not complete successfully.",
            }
        return summary

    if tool_name == "context_tool":
        summary["context"] = _summarize_context(state.get("context"))
    elif tool_name == "pattern_tool":
        summary["pattern_results"] = _summarize_pattern_results(state.get("pattern_results"))
    elif tool_name == "similarity_tool":
        summary["similarity_results"] = _summarize_similarity_results(
            state.get("similarity_results")
        )
    elif tool_name == "reasoning_tool":
        summary["reasoning"] = _summarize_reasoning(state.get("reasoning"))
    elif tool_name == "recommendation_tool":
        summary["recommendations"] = _summarize_recommendations(state.get("recommendations"))
    elif tool_name == "rule_draft_tool":
        summary["rule_draft"] = _summarize_rule_draft(state.get("rule_draft"))
    return summary


def _create_execution_record(
    tool_name: str,
    status: str,
    execution_time_ms: int,
    *,
    input_summary: dict[str, Any],
    output_summary: dict[str, Any],
    error_message: str | None = None,
) -> ToolExecution:
    """Build a ToolExecution record with consistent structure."""
    return ToolExecution(
        tool_name=tool_name,
        input_summary=input_summary,
        output_summary=output_summary,
        execution_time_ms=execution_time_ms,
        status=status,
        error_message=error_message,
        timestamp=utc_now().isoformat(),
    )


def _record_metrics(
    tool_name: str,
    status: str,
    elapsed_seconds: float,
    span: Any,
    *,
    execution_time_ms: int = 0,
    error: str | None = None,
) -> None:
    """Record Prometheus metrics and span attributes for a tool execution."""
    ops_agent_tool_execution_latency_seconds.labels(tool_name=tool_name, status=status).observe(
        elapsed_seconds
    )
    ops_agent_tool_execution_total.labels(tool_name=tool_name, status=status).inc()
    span.set_attribute("status", status)
    if execution_time_ms:
        span.set_attribute("execution_time_ms", execution_time_ms)
    if error:
        span.set_attribute("error", error)


def _append_step(
    state: InvestigationState,
    tool_name: str,
    execution: ToolExecution,
) -> dict[str, Any]:
    """Return state with tool_name appended to completed_steps and execution appended to tool_executions."""
    return {
        **state,
        "completed_steps": [*state["completed_steps"], tool_name],
        "tool_executions": [*state["tool_executions"], execution],
    }


async def executor_node(
    state: InvestigationState,
    registry: ToolRegistry,
) -> InvestigationState:
    """Execute the selected tool and update state."""
    tool_name = state["next_action"]
    settings = get_settings()
    input_summary = _build_input_summary(state, tool_name)

    with tracer.start_as_current_span(f"agent.tool.{tool_name}") as span:
        span.set_attribute("investigation_id", state["investigation_id"])
        span.set_attribute("tool_name", tool_name)

        if not registry.has(tool_name):
            logger.error(
                "Unknown tool requested",
                tool_name=tool_name,
                investigation_id=state["investigation_id"],
            )
            error_msg = f"Unknown tool: {tool_name}"
            execution = _create_execution_record(
                tool_name,
                "FAILED",
                0,
                input_summary=input_summary,
                output_summary=_build_output_summary(
                    state,
                    tool_name,
                    status="FAILED",
                    error_message=error_msg,
                ),
                error_message=error_msg,
            )
            ops_agent_tool_execution_total.labels(tool_name=tool_name, status="FAILED").inc()
            return _append_step(state, tool_name, execution)

        tool = registry.get(tool_name)
        start_time = time.perf_counter()

        try:
            async with asyncio.timeout(settings.langgraph.tool_timeout_seconds):
                updated_state = await tool.execute(state)

            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            execution = _create_execution_record(
                tool_name,
                "SUCCESS",
                execution_time_ms,
                input_summary=input_summary,
                output_summary=_build_output_summary(
                    updated_state,
                    tool_name,
                    status="SUCCESS",
                ),
            )
            _record_metrics(
                tool_name,
                "SUCCESS",
                execution_time_ms / 1000.0,
                span,
                execution_time_ms=execution_time_ms,
            )

            logger.info(
                "Tool executed successfully",
                tool_name=tool_name,
                investigation_id=state["investigation_id"],
                execution_time_ms=execution_time_ms,
            )

            return _append_step(updated_state, tool_name, execution)

        except TimeoutError:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)
            error_msg = f"Tool timed out after {settings.langgraph.tool_timeout_seconds}s"

            logger.warning(
                "Tool timed out",
                tool_name=tool_name,
                investigation_id=state["investigation_id"],
                timeout_seconds=settings.langgraph.tool_timeout_seconds,
            )

            execution = _create_execution_record(
                tool_name,
                "TIMED_OUT",
                execution_time_ms,
                input_summary=input_summary,
                output_summary=_build_output_summary(
                    state,
                    tool_name,
                    status="TIMED_OUT",
                    error_message=error_msg,
                ),
                error_message=error_msg,
            )
            _record_metrics(tool_name, "TIMED_OUT", execution_time_ms / 1000.0, span)

            return _append_step(state, tool_name, execution)

        except Exception as exc:
            execution_time_ms = int((time.perf_counter() - start_time) * 1000)

            logger.error(
                "Tool execution failed",
                tool_name=tool_name,
                investigation_id=state["investigation_id"],
                error=str(exc),
                exc_info=True,
            )

            execution = _create_execution_record(
                tool_name,
                "FAILED",
                execution_time_ms,
                input_summary=input_summary,
                output_summary=_build_output_summary(
                    state,
                    tool_name,
                    status="FAILED",
                    error_message=str(exc),
                ),
                error_message=str(exc),
            )
            _record_metrics(
                tool_name,
                "FAILED",
                execution_time_ms / 1000.0,
                span,
                error=str(exc),
            )

            return _append_step(state, tool_name, execution)
