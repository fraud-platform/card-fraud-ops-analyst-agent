"""Audit stage-by-stage outputs for all seeded E2E scenarios.

Usage:
    uv run python scripts/review_scenario_outputs.py

Reads htmlcov/e2e-seed-manifest.json, executes the same API flow used by
E2E tests for every scenario, and writes htmlcov/stage-audit-report.json.
"""

from __future__ import annotations

import json
import os
import time
from pathlib import Path
from uuid import uuid4

import httpx

from scripts.docker_guard import assert_local_docker_ops_agent


def _resolve_base_url() -> str:
    base_url = os.getenv("E2E_BASE_URL", "http://localhost:8003").strip()
    assert_local_docker_ops_agent(base_url)
    return base_url


BASE_URL = _resolve_base_url()
API_PREFIX = "/api/v1/ops-agent"
MANIFEST_PATH = Path("htmlcov/e2e-seed-manifest.json")
OUTPUT_PATH = Path("htmlcov/stage-audit-report.json")

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


def _extract_run_id(run_response: dict[str, object]) -> str | None:
    errors = run_response.get("errors", {})
    detail = run_response.get("detail", {})
    if isinstance(errors, dict):
        candidate = errors.get("run_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    if isinstance(detail, dict):
        candidate = detail.get("run_id")
        if isinstance(candidate, str) and candidate:
            return candidate
    return None


def _is_low_risk_language(summary: str) -> bool:
    text = " ".join(summary.lower().split())
    return any(marker in text for marker in LOW_RISK_LANGUAGE_MARKERS)


def main() -> None:
    if not MANIFEST_PATH.exists():
        raise FileNotFoundError(
            f"Missing {MANIFEST_PATH}. Run seed script first: "
            "doppler run --config local -- uv run python scripts/seed_test_scenarios.py"
        )

    payload = json.loads(MANIFEST_PATH.read_text(encoding="utf-8"))
    scenarios = payload.get("scenarios")
    if not isinstance(scenarios, dict) or not scenarios:
        raise ValueError(f"Invalid or empty scenarios map in {MANIFEST_PATH}")

    report: dict[str, object] = {
        "generated_at": time.strftime("%Y-%m-%d %H:%M:%S"),
        "base_url": BASE_URL,
        "scenario_count": len(scenarios),
        "rows": [],
    }

    rows: list[dict[str, object]] = []
    with httpx.Client(base_url=BASE_URL, timeout=180) as client:
        for scenario, raw_txn_id in scenarios.items():
            transaction_id = str(raw_txn_id)
            row: dict[str, object] = {
                "scenario": scenario,
                "transaction_id": transaction_id,
                "stages": {},
                "final": {},
                "issues": [],
            }
            stages = row["stages"]
            assert isinstance(stages, dict)

            stages["find_transaction_manifest"] = {
                "status": 200,
                "transaction_id": transaction_id,
            }

            case_id = f"audit-{scenario}-{int(time.time() * 1000)}-{uuid4().hex[:8]}"
            run_body = {"transaction_id": transaction_id, "mode": "quick", "case_id": case_id}
            run_start = time.perf_counter()
            run_response = client.post(f"{API_PREFIX}/investigations/run", json=run_body)
            run_elapsed_ms = (time.perf_counter() - run_start) * 1000

            run_id: str | None = None
            run_state = "new"
            run_payload: dict[str, object] | None = None
            if run_response.status_code in (200, 409):
                try:
                    maybe_payload = run_response.json()
                    if isinstance(maybe_payload, dict):
                        run_payload = maybe_payload
                except json.JSONDecodeError:
                    run_payload = None

            if run_response.status_code == 200 and run_payload:
                maybe_run_id = run_payload.get("run_id")
                if isinstance(maybe_run_id, str) and maybe_run_id:
                    run_id = maybe_run_id
            elif run_response.status_code == 409 and run_payload:
                run_id = _extract_run_id(run_payload)
                run_state = "reused_409"

            stages["run_investigation"] = {
                "status": run_response.status_code,
                "elapsed_ms": round(run_elapsed_ms, 1),
                "run_id": run_id,
                "state": run_state,
                "response_excerpt": run_payload,
            }

            if run_response.status_code not in (200, 409) or not run_id:
                issues = row["issues"]
                assert isinstance(issues, list)
                issues.append(f"run_investigation_failed:{run_response.status_code}")
                rows.append(row)
                continue

            detail_payload: dict[str, object] | None = None
            detail_status = 0
            detail_elapsed_ms = 0.0
            detail_attempts = 0
            for attempt in range(1, 5):
                detail_attempts = attempt
                detail_start = time.perf_counter()
                detail_response = client.get(f"{API_PREFIX}/investigations/{run_id}")
                detail_elapsed_ms = (time.perf_counter() - detail_start) * 1000
                detail_status = detail_response.status_code
                if detail_status == 200:
                    maybe_detail = detail_response.json()
                    if isinstance(maybe_detail, dict):
                        detail_payload = maybe_detail
                    break
                if detail_status == 404 and attempt < 4:
                    time.sleep(1.0)
                    continue
                break

            stages["get_investigation_detail"] = {
                "status": detail_status,
                "attempts": detail_attempts,
                "elapsed_ms": round(detail_elapsed_ms, 1),
            }

            if detail_status != 200 or not detail_payload:
                issues = row["issues"]
                assert isinstance(issues, list)
                issues.append(f"detail_failed:{detail_status}")
                rows.append(row)
                continue

            insight = detail_payload.get("insight", {})
            recommendations = detail_payload.get("recommendations", [])
            evidence = detail_payload.get("evidence", [])
            if not isinstance(insight, dict):
                insight = {}
            if not isinstance(recommendations, list):
                recommendations = []
            if not isinstance(evidence, list):
                evidence = []

            insights_start = time.perf_counter()
            insights_response = client.get(f"{API_PREFIX}/transactions/{transaction_id}/insights")
            insights_elapsed_ms = (time.perf_counter() - insights_start) * 1000
            insights_items_count: int | None = None
            if insights_response.status_code == 200:
                insights_payload = insights_response.json()
                if isinstance(insights_payload, dict):
                    items = insights_payload.get("items")
                    if isinstance(items, list):
                        insights_items_count = len(items)

            stages["get_transaction_insights"] = {
                "status": insights_response.status_code,
                "elapsed_ms": round(insights_elapsed_ms, 1),
                "items_count": insights_items_count,
            }

            worklist_start = time.perf_counter()
            worklist_response = client.get(f"{API_PREFIX}/worklist/recommendations")
            worklist_elapsed_ms = (time.perf_counter() - worklist_start) * 1000
            total_worklist_recommendations: int | None = None
            this_transaction_recommendations = 0
            if worklist_response.status_code == 200:
                worklist_payload = worklist_response.json()
                if isinstance(worklist_payload, dict):
                    all_recommendations = worklist_payload.get("recommendations")
                    if isinstance(all_recommendations, list):
                        total_worklist_recommendations = len(all_recommendations)
                        this_transaction_recommendations = sum(
                            1
                            for recommendation in all_recommendations
                            if isinstance(recommendation, dict)
                            and recommendation.get("transaction_id") == transaction_id
                        )

            stages["get_worklist"] = {
                "status": worklist_response.status_code,
                "elapsed_ms": round(worklist_elapsed_ms, 1),
                "total_recommendations": total_worklist_recommendations,
                "transaction_recommendations": this_transaction_recommendations,
            }

            severity = str(insight.get("severity") or "UNKNOWN")
            summary = str(insight.get("summary") or "")
            model_mode = str(detail_payload.get("model_mode") or "UNKNOWN")

            recommendation_types: list[str] = []
            recommendation_titles: list[str] = []
            for recommendation in recommendations:
                if not isinstance(recommendation, dict):
                    continue
                rec_type = (
                    recommendation.get("type") or recommendation.get("recommendation_type") or ""
                )
                recommendation_types.append(str(rec_type))
                rec_payload = recommendation.get("payload")
                if isinstance(rec_payload, dict):
                    recommendation_titles.append(str(rec_payload.get("title") or ""))
                else:
                    recommendation_titles.append("")

            has_low_risk_language = _is_low_risk_language(summary)
            has_high_priority_actions = any(
                rec_type in {"review_priority", "case_action", "manual_review"}
                for rec_type in recommendation_types
            )
            is_medium_plus = severity in {"MEDIUM", "HIGH", "CRITICAL"}
            contradiction = (is_medium_plus or has_high_priority_actions) and has_low_risk_language

            issues = row["issues"]
            assert isinstance(issues, list)
            if contradiction:
                issues.append("summary_recommendation_contradiction")
            if len(evidence) == 0:
                issues.append("no_structured_evidence")

            row["final"] = {
                "severity": severity,
                "model_mode": model_mode,
                "summary": summary,
                "recommendation_count": len(recommendations),
                "recommendation_types": recommendation_types,
                "recommendation_titles": recommendation_titles,
                "evidence_count": len(evidence),
                "summary_contains_low_risk_language": has_low_risk_language,
                "has_high_priority_actions": has_high_priority_actions,
                "contradiction": contradiction,
            }

            rows.append(row)

    report["rows"] = rows
    report["contradictions"] = [
        str(row.get("scenario"))
        for row in rows
        if isinstance(row.get("issues"), list)
        and "summary_recommendation_contradiction" in row.get("issues", [])
    ]
    report["no_structured_evidence_scenarios"] = [
        str(row.get("scenario"))
        for row in rows
        if isinstance(row.get("issues"), list) and "no_structured_evidence" in row.get("issues", [])
    ]

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding="utf-8")

    contradictions = report["contradictions"]
    no_evidence = report["no_structured_evidence_scenarios"]
    print(f"rows={len(rows)}")
    for row in rows:
        scenario = str(row.get("scenario", "unknown"))
        stages = row.get("stages")
        final = row.get("final")
        issues = row.get("issues")
        if not isinstance(stages, dict):
            stages = {}
        if not isinstance(final, dict):
            final = {}
        if not isinstance(issues, list):
            issues = []

        run_stage = stages.get("run_investigation")
        detail_stage = stages.get("get_investigation_detail")
        insights_stage = stages.get("get_transaction_insights")
        worklist_stage = stages.get("get_worklist")
        if not isinstance(run_stage, dict):
            run_stage = {}
        if not isinstance(detail_stage, dict):
            detail_stage = {}
        if not isinstance(insights_stage, dict):
            insights_stage = {}
        if not isinstance(worklist_stage, dict):
            worklist_stage = {}

        summary = str(final.get("summary") or "")
        summary_snippet = " ".join(summary.split())
        if len(summary_snippet) > 120:
            summary_snippet = f"{summary_snippet[:120]}..."

        print(
            f"{scenario}: "
            f"run={run_stage.get('status')}({run_stage.get('state')},{run_stage.get('elapsed_ms')}ms), "
            f"detail={detail_stage.get('status')}({detail_stage.get('attempts')},{detail_stage.get('elapsed_ms')}ms), "
            f"insights={insights_stage.get('status')}, "
            f"worklist={worklist_stage.get('status')} | "
            f"severity={final.get('severity')} recs={final.get('recommendation_count')} "
            f"evidence={final.get('evidence_count')} contradiction={final.get('contradiction')} | "
            f"issues={issues} | summary={summary_snippet}"
        )

    print(f"Wrote {OUTPUT_PATH}")
    print(f"Contradictions: {len(contradictions)}/{len(rows)}")
    if isinstance(contradictions, list):
        for scenario in contradictions:
            print(f" - {scenario}")
    print(f"No structured evidence: {len(no_evidence)}/{len(rows)}")
    if isinstance(no_evidence, list):
        for scenario in no_evidence:
            print(f" - {scenario}")


if __name__ == "__main__":
    main()
