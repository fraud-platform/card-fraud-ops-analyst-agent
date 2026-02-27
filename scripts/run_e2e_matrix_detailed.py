"""Run 31-scenario E2E matrix and generate detailed collapsible HTML report.

This script preserves the rich request/response per-stage reporting format used by
tests/e2e/reporter.py while running against the seeded 31-scenario manifest.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import time
from collections import Counter, defaultdict
from datetime import datetime
from itertools import zip_longest
from pathlib import Path
from typing import Any
from uuid import uuid4

import httpx

from scripts.docker_guard import (
    assert_local_docker_ops_agent,
    assert_local_docker_transaction_management,
)
from tests.e2e.reporter import E2EReporter

BASE_URL = "http://localhost:8003"
TM_BASE_URL = os.getenv("TM_BASE_URL", "http://localhost:8002")
API_PREFIX = "/api/v1/ops-agent"
MANIFEST_PATH = Path("htmlcov/e2e-seed-manifest.json")
TIMEOUT = 120
TERMINAL_STATUSES = {"COMPLETED", "FAILED", "TIMED_OUT"}
SEV_MEDIUM_PLUS = {"MEDIUM", "HIGH", "CRITICAL"}
HIGH_PRIORITY_TYPES = {"manual_review", "block_card", "escalate"}
LOW_RISK_LANGUAGE_MARKERS = (
    "no red flags",
    "no detected patterns",
    "no patterns",
    "no similar transactions",
    "low risk",
    "routine",
    "typical usage",
    "appears routine",
)
HIGH_RISK_LANGUAGE_MARKERS = (
    "fraud",
    "suspicious",
    "high decline",
    "velocity",
    "rule match",
    "card testing",
    "escalate",
    "high-risk",
    "critical",
)


def _get_default_report_paths() -> tuple[Path, Path, Path]:
    timestamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    base = Path("htmlcov")
    json_path = base / f"e2e-31matrix-report-{timestamp}.json"
    html_path = base / f"e2e-31matrix-report-{timestamp}.html"
    audit_path = base / f"e2e-31matrix-audit-{timestamp}.json"
    return json_path, html_path, audit_path


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run detailed 31-scenario E2E matrix")
    parser.add_argument("--base-url", default=BASE_URL)
    parser.add_argument("--tm-base-url", default=TM_BASE_URL)
    parser.add_argument("--timeout", type=int, default=TIMEOUT)
    parser.add_argument("--manifest", type=Path, default=MANIFEST_PATH)
    default_json, default_html, default_audit = _get_default_report_paths()
    parser.add_argument("--json-report", type=Path, default=default_json)
    parser.add_argument("--html-report", type=Path, default=default_html)
    parser.add_argument("--stage-audit", type=Path, default=default_audit)
    return parser.parse_args()


def _get_git_sha() -> str:
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=False,
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip()[:8]
    except FileNotFoundError:
        pass
    return "unknown"


def _percentile(values: list[float], pct: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    index = max(0, min(len(ordered) - 1, int(len(ordered) * pct + 0.9999) - 1))
    return float(ordered[index])


def _summary_has_low_risk_language(summary: str) -> bool:
    text = " ".join(summary.lower().split())
    has_low_risk = any(marker in text for marker in LOW_RISK_LANGUAGE_MARKERS)
    if not has_low_risk:
        return False
    has_high_risk = any(marker in text for marker in HIGH_RISK_LANGUAGE_MARKERS)
    return not has_high_risk


def _extract_investigation_id(payload: dict[str, Any] | None) -> str | None:
    if not isinstance(payload, dict):
        return None
    for key in ("investigation_id", "run_id"):
        value = payload.get(key)
        if isinstance(value, str) and value:
            return value
    for container_key in ("errors", "detail"):
        container = payload.get(container_key)
        if not isinstance(container, dict):
            continue
        for key in ("existing_investigation_id", "investigation_id", "run_id"):
            value = container.get(key)
            if isinstance(value, str) and value:
                return value
    return None


def _request_json(
    client: httpx.Client,
    method: str,
    url: str,
    *,
    body: dict[str, Any] | None = None,
) -> tuple[int, dict[str, Any] | None, float, str | None]:
    start = time.perf_counter()
    try:
        if method == "POST":
            response = client.post(url, json=body)
        else:
            response = client.get(url)
        elapsed = (time.perf_counter() - start) * 1000
        payload: dict[str, Any] | None = None
        if response.headers.get("content-type", "").startswith("application/json"):
            parsed = response.json()
            if isinstance(parsed, dict):
                payload = parsed
        return response.status_code, payload, elapsed, None
    except httpx.HTTPError as exc:
        elapsed = (time.perf_counter() - start) * 1000
        return 0, None, elapsed, f"{type(exc).__name__}: {exc}"


def _wait_for_readiness(
    base_url: str,
    *,
    timeout_seconds: int = 45,
    step_seconds: float = 1.0,
    require_embedding: bool = False,
) -> None:
    """Wait for service readiness endpoint to return healthy status."""
    deadline = time.time() + timeout_seconds
    last_error = "not checked"
    ready_url = f"{base_url.rstrip('/')}/api/v1/health/ready"
    while time.time() < deadline:
        try:
            response = httpx.get(ready_url, timeout=5.0, trust_env=False)
            if response.status_code == 200:
                payload = response.json() if response.content else {}
                status = str(payload.get("status", "")).lower()
                if status in {"ready", "ok"}:
                    if not require_embedding:
                        return

                    dependencies = _as_dict(payload.get("dependencies"))
                    embedding_ok = payload.get("embedding_service")
                    if embedding_ok is True or dependencies.get("embedding_service") is True:
                        return
                    if embedding_ok is False or dependencies.get("embedding_service") is False:
                        last_error = "embedding_service=false"
                    else:
                        last_error = "embedding_service=missing"
                    time.sleep(step_seconds)
                    continue
                last_error = f"status={status or 'unknown'}"
            else:
                last_error = f"http_{response.status_code}"
        except Exception as exc:  # pragma: no cover - defensive polling loop
            last_error = f"{type(exc).__name__}: {exc}"
        time.sleep(step_seconds)

    if require_embedding:
        raise RuntimeError(
            "Service readiness check failed for "
            f"{ready_url} ({last_error}). "
            "Embedding dependency is required for matrix run; verify VECTOR_API_BASE/"
            "VECTOR_API_KEY (or LLM_API_KEY fallback) and rerun."
        )
    raise RuntimeError(f"Service readiness check failed for {ready_url} ({last_error})")


def _load_manifest(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        raise FileNotFoundError(f"Manifest missing: {path}")
    payload = json.loads(path.read_text(encoding="utf-8"))
    raw = payload.get("matrix_scenarios")
    if not isinstance(raw, dict):
        raw = payload.get("scenarios")
    if not isinstance(raw, dict):
        raise ValueError("Manifest missing scenarios map")

    cases: list[dict[str, str]] = []
    for scenario, transaction_id in raw.items():
        if not isinstance(scenario, str) or not isinstance(transaction_id, str):
            continue
        bucket = "unknown"
        if scenario.startswith("fraud__"):
            bucket = "fraud"
        elif scenario.startswith("likely_fraud__"):
            bucket = "likely_fraud"
        elif scenario.startswith("no_fraud__"):
            bucket = "no_fraud"
        cases.append({"scenario": scenario, "transaction_id": transaction_id, "bucket": bucket})
    return cases


def _as_dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _as_list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _first_non_empty_text(values: list[Any]) -> str:
    for value in values:
        if isinstance(value, str):
            text = value.strip()
            if text:
                return text
    return ""


def _extract_latest_insight(insights_payload: dict[str, Any] | None) -> dict[str, Any]:
    payload = _as_dict(insights_payload)
    insights = _as_list(payload.get("insights"))
    if insights and isinstance(insights[0], dict):
        return insights[0]
    return {}


def _summarize_evidence(evidence: list[Any]) -> list[dict[str, Any]]:
    summary_rows: list[dict[str, Any]] = []
    for item in evidence:
        item_dict = _as_dict(item)
        payload = _as_dict(item_dict.get("evidence_payload"))
        supporting = _as_dict(payload.get("supporting_data"))
        category = str(
            item_dict.get("category")
            or item_dict.get("evidence_kind")
            or item_dict.get("kind")
            or payload.get("category")
            or "unknown"
        )
        description = str(
            item_dict.get("description")
            or payload.get("description")
            or supporting.get("description")
            or ""
        )
        strength_raw = (
            item_dict.get("strength")
            or payload.get("strength")
            or supporting.get("overall_confidence")
            or supporting.get("overall_score")
            or 0.0
        )
        try:
            strength = round(float(strength_raw), 3)
        except TypeError, ValueError:
            strength = 0.0
        summary_rows.append(
            {
                "category": category,
                "strength": strength,
                "description": description[:240],
            }
        )
    return summary_rows


def _extract_summary(
    detail_payload: dict[str, Any],
    latest_insight: dict[str, Any],
) -> str:
    reasoning = _as_dict(detail_payload.get("reasoning"))
    findings = _as_list(reasoning.get("key_findings"))
    finding_text = "; ".join(str(item).strip() for item in findings if str(item).strip())
    return _first_non_empty_text(
        [
            reasoning.get("summary"),
            reasoning.get("narrative"),
            finding_text,
            latest_insight.get("summary"),
        ]
    )


def _extract_agent_trace(detail_payload: dict[str, Any]) -> dict[str, Any]:
    planner_decisions = [
        item for item in _as_list(detail_payload.get("planner_decisions")) if isinstance(item, dict)
    ]
    tool_executions = [
        item for item in _as_list(detail_payload.get("tool_executions")) if isinstance(item, dict)
    ]
    planner_path = [str(item.get("selected_tool") or "") for item in planner_decisions]
    tool_path = [
        f"{item.get('tool_name', 'unknown')}:{item.get('status', 'UNKNOWN')}"
        for item in tool_executions
    ]
    failed_tools = [
        {
            "tool_name": item.get("tool_name", "unknown"),
            "status": item.get("status", "UNKNOWN"),
            "error_message": item.get("error_message"),
        }
        for item in tool_executions
        if str(item.get("status", "")).upper() in {"FAILED", "TIMED_OUT"}
    ]
    return {
        "planner_decisions": planner_decisions,
        "tool_executions": tool_executions,
        "planner_path": planner_path,
        "tool_path": tool_path,
        "failed_tools": failed_tools,
    }


def _agent_stage_status(tool_status: str) -> int:
    normalized = tool_status.upper()
    if normalized == "SUCCESS":
        return 200
    if normalized == "TIMED_OUT":
        return 408
    return 500


def _non_empty_dict(value: Any) -> bool:
    return isinstance(value, dict) and bool(value)


def _is_similarity_degraded(similarity_results: dict[str, Any]) -> bool:
    if not similarity_results:
        return False
    if similarity_results.get("skipped"):
        return True
    reason = similarity_results.get("reason", "")
    if "embedding_or_similarity_failed" in str(reason).lower():
        return True
    error_msg = similarity_results.get("error", "")
    if "embedding" in str(error_msg).lower() or "similarity" in str(error_msg).lower():
        return True
    return False


def _is_context_complete(context: dict[str, Any]) -> bool:
    if not context:
        return False
    features = _as_dict(context.get("features"))
    transaction = _as_dict(context.get("transaction"))

    transaction_id = (
        context.get("transaction_id")
        or features.get("transaction_id")
        or transaction.get("transaction_id")
    )
    amount = features.get("amount")
    if amount is None:
        amount = transaction.get("amount")
    currency = features.get("currency") or transaction.get("currency")
    card_id = features.get("card_id") or transaction.get("card_id")
    merchant_id = features.get("merchant_id") or transaction.get("merchant_id")
    decision = features.get("decision") or transaction.get("decision") or transaction.get("status")

    required_values = [transaction_id, amount, currency, card_id, merchant_id, decision]
    return all(value is not None and str(value).strip() != "" for value in required_values)


REASONING_FALLBACK_MARKERS = (
    "no transaction data provided",
    "no context available",
    "unable to retrieve context",
    "context not available",
)


def _is_reasoning_fallback(reasoning: dict[str, Any], context: dict[str, Any]) -> bool:
    if not reasoning:
        return False
    if not context:
        return True
    summary = str(reasoning.get("summary", "")).lower()
    narrative = str(reasoning.get("narrative", "")).lower()
    combined = summary + narrative
    has_fallback_marker = any(marker in combined for marker in REASONING_FALLBACK_MARKERS)
    return has_fallback_marker


def _compute_kpis(
    rows: list[dict[str, Any]],
    run_latencies: list[float],
) -> dict[str, dict[str, Any]]:
    total = len(rows)
    if total == 0:
        return {}

    passed_scenarios = sum(1 for r in rows if not r.get("issues"))
    context_complete = sum(1 for r in rows if "context_incomplete" not in r.get("issues", []))
    tool_failures = sum(1 for r in rows if any("tool_failure" in i for i in r.get("issues", [])))
    similarity_degraded = sum(1 for r in rows if "similarity_degraded" in r.get("issues", []))
    reasoning_fallback = sum(1 for r in rows if "reasoning_fallback" in r.get("issues", []))

    all_latencies = [r.get("run_latency_ms", 0) or 0 for r in rows if r.get("run_latency_ms")]
    latency_p95 = _percentile(all_latencies, 0.95) if all_latencies else 0.0

    trace_coverage = sum(1 for r in rows if r.get("tool_execution_count", 0) > 0)

    return {
        "kpi_e2e_scenarios_pass_rate": {
            "value": passed_scenarios / total,
            "target": "1.0",
            "pass": passed_scenarios == total,
            "description": "passed_scenarios / total_scenarios",
        },
        "kpi_context_completeness_rate": {
            "value": context_complete / total,
            "target": ">= 0.99",
            "pass": context_complete / total >= 0.99,
            "description": "scenarios with complete context fields",
        },
        "kpi_tool_failure_rate": {
            "value": tool_failures / total,
            "target": "0.0",
            "pass": tool_failures == 0,
            "description": "scenarios with failed tool executions",
        },
        "kpi_similarity_degraded_rate": {
            "value": similarity_degraded / total,
            "target": "0.0",
            "pass": similarity_degraded == 0,
            "description": "scenarios with degraded similarity/embedding",
        },
        "kpi_reasoning_fallback_rate": {
            "value": reasoning_fallback / total,
            "target": "<= 0.02",
            "pass": reasoning_fallback / total <= 0.02,
            "description": "scenarios with reasoning fallback markers",
        },
        "kpi_latency_p95_investigation_ms": {
            "value": latency_p95,
            "target": "< 60000",
            "pass": latency_p95 < 60000,
            "description": "P95 investigation latency in ms",
        },
        "kpi_trace_coverage_rate": {
            "value": trace_coverage / total,
            "target": ">= 0.95",
            "pass": trace_coverage / total >= 0.95,
            "description": "scenarios with agent trace data",
        },
    }


def run() -> int:
    args = _parse_args()
    try:
        assert_local_docker_ops_agent(args.base_url)
        assert_local_docker_transaction_management(args.tm_base_url)
        _wait_for_readiness(args.base_url)
        _wait_for_readiness(args.tm_base_url)
    except (RuntimeError, ValueError) as exc:
        print(f"[PRECHECK] {exc}")
        return 2

    cases = _load_manifest(args.manifest)
    git_sha = _get_git_sha()
    reporter = E2EReporter(
        title="E2E Scenarios Report (31 Scenario Matrix)",
        metadata={"git_sha": git_sha, "base_url": args.base_url, "tm_base_url": args.tm_base_url},
    )

    rows: list[dict[str, Any]] = []
    with httpx.Client(base_url=args.base_url, timeout=args.timeout, trust_env=False) as client:
        for idx, case in enumerate(cases, start=1):
            scenario = case["scenario"]
            transaction_id = case["transaction_id"]
            bucket = case["bucket"]
            case_id = f"matrix-detailed-{idx:03d}-{uuid4().hex[:8]}"
            reporter.begin_scenario(scenario)

            reporter.record_stage(
                stage_name="Resolve Scenario Transaction",
                status=200,
                elapsed_ms=0,
                request_method="INTERNAL",
                request_url=str(args.manifest),
                response_status=200,
                response_body={
                    "scenario": scenario,
                    "transaction_id": transaction_id,
                    "bucket": bucket,
                },
            )

            row: dict[str, Any] = {
                "scenario": scenario,
                "bucket": bucket,
                "transaction_id": transaction_id,
                "run_status": None,
                "detail_status": None,
                "run_latency_ms": None,
                "detail_latency_ms": None,
                "detail_attempts": 0,
                "status": "UNKNOWN",
                "severity": "UNKNOWN",
                "recommendation_count": 0,
                "recommendation_types": [],
                "evidence_count": 0,
                "insight_evidence_count": 0,
                "summary": "",
                "planner_step_count": 0,
                "tool_execution_count": 0,
                "planner_path": [],
                "tool_path": [],
                "failed_tools": [],
                "similarity_match_count": 0,
                "similarity_overall_score": 0.0,
                "vector_skipped": False,
                "empty_stage_io_steps": 0,
                "issues": [],
            }

            run_body = {"transaction_id": transaction_id, "mode": "quick", "case_id": case_id}
            run_status, run_payload, run_ms, run_error = _request_json(
                client,
                "POST",
                f"{API_PREFIX}/investigations/run",
                body=run_body,
            )
            row["run_status"] = run_status
            row["run_latency_ms"] = round(run_ms, 1)
            reporter.record_stage(
                stage_name="Run Investigation",
                status=run_status if run_status else 0,
                elapsed_ms=run_ms,
                request_method="POST",
                request_url=f"{args.base_url}{API_PREFIX}/investigations/run",
                request_body=run_body,
                response_status=run_status,
                response_body=run_payload,
                error=run_error,
            )

            if run_error:
                row["issues"].append(f"run_transport_error:{run_error}")
                rows.append(row)
                continue

            inv_id = _extract_investigation_id(run_payload)
            if run_status not in {200, 409} or not inv_id:
                row["issues"].append(f"run_failed:{run_status}")
                rows.append(row)
                continue

            if run_status == 409:
                resume_status, resume_payload, resume_ms, resume_error = _request_json(
                    client,
                    "POST",
                    f"{API_PREFIX}/investigations/{inv_id}/resume",
                )
                reporter.record_stage(
                    stage_name="Resume Existing Investigation",
                    status=resume_status if resume_status else 0,
                    elapsed_ms=resume_ms,
                    request_method="POST",
                    request_url=f"{args.base_url}{API_PREFIX}/investigations/{inv_id}/resume",
                    response_status=resume_status,
                    response_body=resume_payload,
                    error=resume_error,
                    notes=["[RECOVERY] run returned 409; attempting resume for existing run"],
                )
                if resume_error:
                    row["issues"].append(f"resume_transport_error:{resume_error}")
                    rows.append(row)
                    continue
                if resume_status not in {200, 202, 409}:
                    row["issues"].append(f"resume_failed:{resume_status}")
                    rows.append(row)
                    continue

            detail_payload: dict[str, Any] | None = None
            detail_status = 0
            detail_ms = 0.0
            detail_error: str | None = None
            detail_attempts = 0
            deadline = time.time() + max(args.timeout, 40)
            while True:
                detail_attempts += 1
                detail_status, detail_payload, detail_ms, detail_error = _request_json(
                    client,
                    "GET",
                    f"{API_PREFIX}/investigations/{inv_id}",
                )
                reporter.record_stage(
                    stage_name=f"Get Investigation Detail (attempt {detail_attempts})",
                    status=detail_status if detail_status else 0,
                    elapsed_ms=detail_ms,
                    request_method="GET",
                    request_url=f"{args.base_url}{API_PREFIX}/investigations/{inv_id}",
                    response_status=detail_status,
                    response_body=detail_payload,
                    error=detail_error,
                )
                state = ""
                if isinstance(detail_payload, dict):
                    state = str(detail_payload.get("status") or "")
                if detail_error:
                    if time.time() >= deadline:
                        break
                    time.sleep(0.75)
                    continue
                if detail_status == 200 and state in TERMINAL_STATUSES:
                    break
                if time.time() >= deadline:
                    break
                time.sleep(0.75)

            row["detail_status"] = detail_status
            row["detail_latency_ms"] = round(detail_ms, 1)
            row["detail_attempts"] = detail_attempts
            if detail_error:
                row["issues"].append(f"detail_transport_error:{detail_error}")
                rows.append(row)
                continue
            if detail_status != 200 or not isinstance(detail_payload, dict):
                row["issues"].append(f"detail_failed:{detail_status}")
                rows.append(row)
                continue

            insights_status, insights_payload, insights_ms, insights_error = _request_json(
                client,
                "GET",
                f"{API_PREFIX}/transactions/{transaction_id}/insights",
            )
            reporter.record_stage(
                stage_name="Get Transaction Insights",
                status=insights_status if insights_status else 0,
                elapsed_ms=insights_ms,
                request_method="GET",
                request_url=f"{args.base_url}{API_PREFIX}/transactions/{transaction_id}/insights",
                response_status=insights_status,
                response_body=insights_payload,
                error=insights_error,
            )

            worklist_status, worklist_payload, worklist_ms, worklist_error = _request_json(
                client,
                "GET",
                f"{API_PREFIX}/worklist/recommendations?limit=50",
            )
            reporter.record_stage(
                stage_name="Get Worklist",
                status=worklist_status if worklist_status else 0,
                elapsed_ms=worklist_ms,
                request_method="GET",
                request_url=f"{args.base_url}{API_PREFIX}/worklist/recommendations?limit=50",
                response_status=worklist_status,
                response_body=worklist_payload,
                error=worklist_error,
            )

            latest_insight = _extract_latest_insight(insights_payload)
            recommendations = detail_payload.get("recommendations")
            if not isinstance(recommendations, list):
                recommendations = []
            detail_evidence = _as_list(detail_payload.get("evidence"))
            insight_evidence = _as_list(latest_insight.get("evidence"))
            evidence_summary = _summarize_evidence(detail_evidence or insight_evidence)
            trace = _extract_agent_trace(detail_payload)
            similarity_results = _as_dict(detail_payload.get("similarity_results"))
            similarity_matches = _as_list(similarity_results.get("matches"))
            try:
                row["similarity_overall_score"] = float(
                    similarity_results.get("overall_score", 0.0) or 0.0
                )
            except TypeError, ValueError:
                row["similarity_overall_score"] = 0.0
            row["similarity_match_count"] = len(similarity_matches)
            row["vector_skipped"] = bool(similarity_results.get("skipped"))
            row["empty_stage_io_steps"] = sum(
                1
                for execution in trace["tool_executions"]
                if not _non_empty_dict(execution.get("input_summary"))
                and not _non_empty_dict(execution.get("output_summary"))
            )

            for step_number, pair in enumerate(
                zip_longest(trace["planner_decisions"], trace["tool_executions"]),
                start=1,
            ):
                planner_decision, tool_execution = pair
                planner = planner_decision if isinstance(planner_decision, dict) else {}
                execution = tool_execution if isinstance(tool_execution, dict) else {}
                selected_tool = str(
                    planner.get("selected_tool")
                    or execution.get("tool_name")
                    or f"step_{step_number}"
                )
                if selected_tool == "COMPLETE" and not execution:
                    continue

                tool_status = str(execution.get("status") or "UNKNOWN")
                stage_status = _agent_stage_status(tool_status) if execution else 200
                elapsed_ms_raw = execution.get("execution_time_ms", 0) if execution else 0
                try:
                    elapsed_ms = float(elapsed_ms_raw)
                except TypeError, ValueError:
                    elapsed_ms = 0.0

                reporter.record_stage(
                    stage_name=f"Agent Step {step_number}: {selected_tool}",
                    status=stage_status,
                    elapsed_ms=elapsed_ms,
                    request_method="AGENT",
                    request_url=selected_tool,
                    request_body={
                        "planner": {
                            "selected_tool": selected_tool,
                            "reason": planner.get("reason"),
                            "confidence": planner.get("confidence"),
                        },
                        "tool_input": execution.get("input_summary", {}),
                    },
                    response_status=stage_status,
                    response_body={
                        "tool_name": execution.get("tool_name", selected_tool),
                        "tool_status": tool_status,
                        "tool_output": execution.get("output_summary", {}),
                        "error_message": execution.get("error_message"),
                    },
                    notes=[
                        f"[PLANNER] {planner.get('reason')}"
                        if planner.get("reason")
                        else "[PLANNER] no reason captured"
                    ],
                )

            recommendation_types: list[str] = []
            for rec in recommendations:
                if isinstance(rec, dict):
                    recommendation_types.append(
                        str(rec.get("type") or rec.get("recommendation_type") or "")
                    )

            status = str(detail_payload.get("status") or "UNKNOWN")
            severity = str(
                detail_payload.get("severity")
                or _as_dict(detail_payload.get("reasoning")).get("risk_level")
                or latest_insight.get("severity")
                or "UNKNOWN"
            )
            summary = _extract_summary(detail_payload, latest_insight)
            row["status"] = status
            row["severity"] = severity
            row["summary"] = summary
            row["recommendation_count"] = len(recommendations)
            row["recommendation_types"] = recommendation_types
            row["evidence_count"] = len(detail_evidence)
            row["insight_evidence_count"] = len(insight_evidence)
            row["planner_step_count"] = len(trace["planner_decisions"])
            row["tool_execution_count"] = len(trace["tool_executions"])
            row["planner_path"] = trace["planner_path"]
            row["tool_path"] = trace["tool_path"]
            row["failed_tools"] = trace["failed_tools"]

            high_priority = any(t in HIGH_PRIORITY_TYPES for t in recommendation_types)
            contradiction = (
                severity in SEV_MEDIUM_PLUS or high_priority
            ) and _summary_has_low_risk_language(summary)

            if status not in TERMINAL_STATUSES:
                row["issues"].append(f"run_not_terminal:{status}")
            if bucket == "fraud" and severity not in SEV_MEDIUM_PLUS:
                row["issues"].append("fraud_underclassified_low")
            if bucket == "no_fraud" and severity in SEV_MEDIUM_PLUS:
                row["issues"].append("no_fraud_overescalated")
            if bucket == "likely_fraud" and len(recommendations) == 0:
                row["issues"].append("likely_no_recommendation")
            if contradiction:
                row["issues"].append("summary_recommendation_contradiction")
            if len(detail_evidence) == 0 and len(insight_evidence) == 0:
                row["issues"].append("no_structured_evidence")
            run_planner_steps = len(_as_list(_as_dict(run_payload).get("planner_decisions")))
            run_tool_steps = len(_as_list(_as_dict(run_payload).get("tool_executions")))
            if (run_planner_steps > 0 and row["planner_step_count"] == 0) or (
                run_tool_steps > 0 and row["tool_execution_count"] == 0
            ):
                row["issues"].append("detail_missing_agent_trace")
            if (
                row["tool_execution_count"] > 0
                and row["empty_stage_io_steps"] == row["tool_execution_count"]
            ):
                row["issues"].append("agent_stage_io_missing")

            if trace["failed_tools"]:
                row["issues"].append(f"tool_failure:{len(trace['failed_tools'])}")

            similarity_results = _as_dict(detail_payload.get("similarity_results"))
            if _is_similarity_degraded(similarity_results):
                row["issues"].append("similarity_degraded")

            context = _as_dict(detail_payload.get("context"))
            if not _is_context_complete(context):
                row["issues"].append("context_incomplete")

            reasoning = _as_dict(detail_payload.get("reasoning"))
            if _is_reasoning_fallback(reasoning, context):
                row["issues"].append("reasoning_fallback")

            reporter.record_stage(
                stage_name="Fraud Analyst Assessment",
                status=200 if not row["issues"] else 400,
                elapsed_ms=0,
                request_method="ANALYSIS",
                request_url="assessment",
                response_status=200 if not row["issues"] else 400,
                response_body={
                    "status": status,
                    "severity": severity,
                    "recommendation_count": len(recommendations),
                    "evidence_count": len(detail_evidence),
                    "insight_evidence_count": len(insight_evidence),
                    "issues": row["issues"],
                    "summary": summary,
                    "evidence_summary": evidence_summary[:10],
                    "planner_path": row["planner_path"],
                    "tool_path": row["tool_path"],
                    "failed_tools": row["failed_tools"],
                    "similarity": {
                        "match_count": row["similarity_match_count"],
                        "overall_score": row["similarity_overall_score"],
                        "skipped": row["vector_skipped"],
                    },
                    "empty_stage_io_steps": row["empty_stage_io_steps"],
                    "reasoning": _as_dict(detail_payload.get("reasoning")),
                },
                notes=[
                    "[PASS] No issues"
                    if not row["issues"]
                    else f"[FAIL] {', '.join(row['issues'])}"
                ],
            )
            rows.append(row)
            print(
                f"[{idx:02d}/{len(cases)}] {scenario} bucket={bucket} status={status} "
                f"severity={severity} recs={len(recommendations)} detail_evidence={len(detail_evidence)} "
                f"insight_evidence={len(insight_evidence)} issues={row['issues']}"
            )

    issue_counter = Counter(issue for row in rows for issue in row.get("issues", []))
    by_bucket: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_bucket[str(row.get("bucket"))].append(row)

    severity_by_bucket: dict[str, dict[str, int]] = {}
    for bucket, bucket_rows in by_bucket.items():
        severity_by_bucket[bucket] = dict(
            sorted(Counter(str(r.get("severity", "UNKNOWN")) for r in bucket_rows).items())
        )

    status_counts = dict(sorted(Counter(str(r.get("status", "UNKNOWN")) for r in rows).items()))
    run_latencies = [
        float(r["run_latency_ms"]) for r in rows if r.get("run_latency_ms") is not None
    ]
    detail_latencies = [
        float(r["detail_latency_ms"]) for r in rows if r.get("detail_latency_ms") is not None
    ]

    report = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "git_sha": git_sha,
        "base_url": args.base_url,
        "tm_base_url": args.tm_base_url,
        "scenario_count": len(rows),
        "bucket_counts": {k: len(v) for k, v in by_bucket.items()},
        "status_counts": status_counts,
        "severity_by_bucket": severity_by_bucket,
        "issue_counts": dict(sorted(issue_counter.items())),
        "latency_ms": {
            "run_p95": round(_percentile(run_latencies, 0.95), 1),
            "detail_p95": round(_percentile(detail_latencies, 0.95), 1),
            "run_avg": round(sum(run_latencies) / len(run_latencies), 1) if run_latencies else 0.0,
            "detail_avg": round(sum(detail_latencies) / len(detail_latencies), 1)
            if detail_latencies
            else 0.0,
        },
        "rows": rows,
    }

    kpis = _compute_kpis(rows, run_latencies)
    report["kpis"] = kpis
    all_kpis_pass = all(bool(metric.get("pass")) for metric in kpis.values())

    reporter.begin_scenario("Evaluate Acceptance KPIs")
    reporter.record_stage(
        stage_name="Evaluate Acceptance KPIs",
        status=200 if all_kpis_pass else 400,
        elapsed_ms=0,
        request_method="ANALYSIS",
        request_url="kpi_evaluation",
        response_status=200 if all_kpis_pass else 400,
        response_body={"kpis": kpis},
        notes=[
            f"[KPI] pass_rate={kpis['kpi_e2e_scenarios_pass_rate']['value']:.2%}",
            "[PASS] All KPI gates passed" if all_kpis_pass else "[FAIL] KPI gate failed",
        ],
    )

    for sc in reporter._scenarios:
        if sc.name == "Evaluate Acceptance KPIs":
            continue
        has_kpi_issues = any(
            issue.startswith("tool_failure")
            or issue == "similarity_degraded"
            or issue == "context_incomplete"
            or issue == "reasoning_fallback"
            for row in rows
            if row["scenario"] == sc.name
            for issue in row.get("issues", [])
        )
        if has_kpi_issues:
            for stage in sc.stages:
                if stage.name == "Fraud Analyst Assessment":
                    stage.status = 400
                    break

    stage_rows: list[dict[str, Any]] = []
    for scenario in reporter._scenarios:
        stage_rows.append(
            {
                "scenario": scenario.name,
                "passed": scenario.passed,
                "stage_count": len(scenario.stages),
                "stages": [
                    {
                        "name": s.name,
                        "status": s.status,
                        "elapsed_ms": round(s.elapsed_ms, 1),
                        "request_method": s.request_method,
                        "request_url": s.request_url,
                        "request_body": s.request_body,
                        "response_status": s.response_status,
                        "response_body": s.response_body,
                        "error": s.error,
                        "notes": s.notes,
                    }
                    for s in scenario.stages
                ],
            }
        )
    stage_audit = {
        "generated_at": report["generated_at"],
        "git_sha": git_sha,
        "base_url": args.base_url,
        "tm_base_url": args.tm_base_url,
        "scenario_count": len(stage_rows),
        "rows": stage_rows,
    }

    args.json_report.parent.mkdir(parents=True, exist_ok=True)
    args.json_report.write_text(json.dumps(report, indent=2), encoding="utf-8")
    args.stage_audit.parent.mkdir(parents=True, exist_ok=True)
    args.stage_audit.write_text(json.dumps(stage_audit, indent=2), encoding="utf-8")
    reporter.write_html(args.html_report)

    print("\n=== DETAILED MATRIX SUMMARY ===")
    print(f"scenario_count={len(rows)}")
    print(f"bucket_counts={report['bucket_counts']}")
    print(f"status_counts={status_counts}")
    print(f"severity_by_bucket={severity_by_bucket}")
    print(f"issue_counts={report['issue_counts']}")
    print(f"latency_ms={report['latency_ms']}")
    print(f"kpi_all_pass={all_kpis_pass}")
    print(f"json_report={args.json_report}")
    print(f"stage_audit={args.stage_audit}")
    print(f"html_report={args.html_report}")
    return 0 if all_kpis_pass else 1


if __name__ == "__main__":
    raise SystemExit(run())
