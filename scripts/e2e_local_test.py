"""End-to-end local test against a running server + Ollama.

Usage (requires server running via `uv run doppler-local`):
    doppler run --project card-fraud-ops-analyst-agent --config local -- \
        python scripts/e2e_local_test.py

Or via CLI wrapper:
    uv run e2e-local

Generates HTML report: htmlcov/e2e-report.html
"""

from __future__ import annotations

import html
import json
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import httpx

from scripts.docker_guard import assert_local_docker_ops_agent


def _resolve_base_url() -> str:
    base_url = os.getenv("E2E_BASE_URL", "http://localhost:8003").strip()
    assert_local_docker_ops_agent(base_url)
    return base_url


BASE_URL = _resolve_base_url()
API_PREFIX = "/api/v1/ops-agent"
OLLAMA_URL = os.getenv("OLLAMA_URL", "http://localhost:11434")
TM_BASE_URL = os.getenv("TM_BASE_URL", "http://localhost:8002")  # Transaction Management API
TIMEOUT = 180  # generous for local LLM
REPORT_DIR = Path("htmlcov")
REPORT_FILE = REPORT_DIR / "e2e-report.html"


class E2EReporter:
    """Generates HTML report for E2E test results."""

    def __init__(self) -> None:
        self.stages: list[dict] = []
        self.start_time = time.perf_counter()
        self.ollama_ok = False
        self.server_ok = False
        self.transaction_id = ""

    def log(self, stage: str, msg: str, elapsed_ms: float | None = None) -> None:
        """Record a log message."""
        elapsed = f" ({elapsed_ms:.0f}ms)" if elapsed_ms is not None else ""
        print(f"  [{stage}]{elapsed} {msg}")

    def record_stage(
        self,
        stage_name: str,
        status: int,
        elapsed_ms: float,
        request_method: str,
        request_url: str,
        request_body: dict | None = None,
        response_status: int | None = None,
        response_body: dict | None = None,
        response_headers: dict | None = None,
        error: str | None = None,
    ) -> None:
        """Record a test stage with full request/response details."""
        stage = {
            "name": stage_name,
            "status": status,
            "elapsed_ms": elapsed_ms,
            "request": {
                "method": request_method,
                "url": request_url,
                "body": request_body,
            },
            "response": {
                "status": response_status,
                "body": response_body,
                "headers": response_headers,
            },
            "error": error,
        }
        self.stages.append(stage)

        self.log(stage_name.upper(), f"HTTP {status}", elapsed_ms)

    def generate_html(self) -> str:
        """Generate HTML report."""
        total_elapsed = (time.perf_counter() - self.start_time) * 1000
        passed_count = sum(1 for s in self.stages if s["status"] == 200)
        failed_count = len(self.stages) - passed_count

        html_content = f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>E2E Test Report - {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}</title>
    <style>
        * {{ box-sizing: border-box; }}
        body {{
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
            line-height: 1.6;
            margin: 0;
            padding: 20px;
            background: #f5f5f5;
        }}
        .container {{
            max-width: 1400px;
            margin: 0 auto;
            background: white;
            border-radius: 8px;
            padding: 30px;
            box-shadow: 0 2px 10px rgba(0,0,0,1);
        }}
        h1 {{
            color: #1a1a1a;
            border-bottom: 2px solid #e0e0e0;
            padding-bottom: 10px;
            margin-bottom: 20px;
        }}
        .summary {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(200px, 1fr));
            gap: 15px;
            margin-bottom: 30px;
        }}
        .summary-card {{
            background: #f8f9fa;
            border: 1px solid #e1e4e8;
            border-radius: 6px;
            padding: 15px;
        }}
        .summary-card h3 {{
            margin: 0 0 10px 0;
            color: #374151;
            font-size: 14px;
            text-transform: uppercase;
            letter-spacing: 0.5px;
        }}
        .summary-card .value {{
            font-size: 24px;
            font-weight: bold;
            color: #1a1a1a;
        }}
        .summary-card.pass .value {{ color: #059669; }}
        .summary-card.fail .value {{ color: #dc2626; }}
        .stages {{
            margin-top: 30px;
        }}
        .stage {{
            margin-bottom: 20px;
            border: 1px solid #e5e7eb;
            border-radius: 6px;
            overflow: hidden;
        }}
        .stage.pass {{ border-left: 4px solid #059669; }}
        .stage.fail {{ border-left: 4px solid #dc2626; }}
        .stage-header {{
            background: #f8f9fa;
            padding: 12px 15px;
            display: flex;
            justify-content: space-between;
            align-items: center;
            font-weight: 600;
        }}
        .stage-header .status-pass {{ color: #059669; }}
        .stage-header .status-fail {{ color: #dc2626; }}
        .stage-body {{
            padding: 15px;
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 20px;
        }}
        .request-response {{
            display: grid;
            grid-template-columns: 1fr 1fr;
            gap: 15px;
        }}
        .http-details {{
            background: #fafafa;
            border: 1px solid #e0e0e0;
            border-radius: 4px;
            overflow: hidden;
        }}
        .http-details h4 {{
            margin: 0 0 10px 0;
            padding: 8px 12px;
            background: #e8e8e8;
            color: #1a1a1a;
            font-size: 12px;
            text-transform: uppercase;
        }}
        .http-details pre {{
            margin: 0;
            padding: 12px;
            overflow-x: auto;
            font-size: 12px;
            line-height: 1.4;
        }}
        .json-key {{ color: #0d47a1; }}
        .json-string {{ color: #032f62; }}
        .json-number {{ color: #1f6419; }}
        .json-boolean {{ color: #0d47a1; }}
        .json-null {{ color: #999; }}
        .badge {{
            display: inline-block;
            padding: 3px 8px;
            border-radius: 12px;
            font-size: 11px;
            font-weight: 600;
            margin-left: 8px;
        }}
        .badge.get {{ background: #d1fae5; color: #059669; }}
        .badge.post {{ background: #dbeafe; color: #047857; }}
        .badge.put {{ background: #fef3c7; color: #92400e; }}
        .badge.delete {{ background: #fee2e2; color: #dc2626; }}
        .badge.patch {{ background: #e0e7ff; color: #4338ca; }}
    </style>
</head>
<body>
    <div class="container">
        <h1>🧪 E2E Test Report</h1>
        <p style="color: #666; margin-bottom: 20px;">
            Generated: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")} |
            Total Duration: {total_elapsed:.0f}ms |
            Transaction ID: <code style="background:#f4f4f4;padding:4px 8px;border-radius:4px;">{self.transaction_id or "N/A"}</code>
        </p>

        <div class="summary">
            <div class="summary-card {"pass" if failed_count == 0 else "fail"}">
                <h3>Total Stages</h3>
                <div class="value">{len(self.stages)}</div>
            </div>
            <div class="summary-card pass">
                <h3>Passed</h3>
                <div class="value">{passed_count}</div>
            </div>
            <div class="summary-card fail">
                <h3>Failed</h3>
                <div class="value">{failed_count}</div>
            </div>
            <div class="summary-card">
                <h3>Ollama</h3>
                <div class="value">{"✅" if self.ollama_ok else "❌"}</div>
            </div>
            <div class="summary-card">
                <h3>LLM Mode</h3>
                <div class="value">{self._get_llm_mode() or "N/A"}</div>
            </div>
        </div>

        <div class="stages">
            {self._generate_stages_html()}
        </div>

        <footer style="margin-top: 40px; padding-top: 20px; border-top: 1px solid #e5e7eb; color: #999; font-size: 12px;">
            Card Fraud Ops Analyst Agent - E2E Test Report
        </footer>
    </div>
</body>
</html>"""
        return html_content

    def _generate_stages_html(self) -> str:
        """Generate HTML for all stages."""
        stages_html = []
        for stage in self.stages:
            stage_class = "pass" if stage["status"] == 200 else "fail"
            status_text = "✅ PASS" if stage["status"] == 200 else "❌ FAIL"
            status_class = "status-pass" if stage["status"] == 200 else "status-fail"

            req = stage["request"]
            resp = stage["response"]

            method_badge = f'<span class="badge {req["method"].lower()}">{req["method"]}</span>'

            request_html = f"""
                <div class="http-details">
                    <h4>Request</h4>
                    <div style="padding-bottom: 8px;">
                        <strong>Method:</strong> {method_badge}
                        <strong style="margin-left: 15px;">URL:</strong> <code style="background:#f4f4f4;padding:2px 6px;border-radius:3px;font-size:11px;">{html.escape(req["url"])}</code>
                    </div>
                    {self._format_json(req["body"], "Request Body") if req["body"] else "<p><em>No body</em></p>"}
                </div>
            """

            response_html = ""
            if stage["error"]:
                response_html = f"""
                    <div class="http-details">
                        <h4>Error</h4>
                        <pre style="color: #dc2626;">{html.escape(stage["error"])}</pre>
                    </div>
                """
            elif resp["status"]:
                status_badge = f'<span class="badge {self._status_to_badge(resp["status"])}">{resp["status"]}</span>'
                response_html = f"""
                <div class="http-details">
                    <h4>Response</h4>
                    <div style="padding-bottom: 8px;">
                        <strong>Status:</strong> {status_badge}
                        <strong style="margin-left: 15px;">Duration:</strong> {stage["elapsed_ms"]:.0f}ms
                    </div>
                    {self._format_json(resp["body"], "Response Body") if resp["body"] else "<p><em>Empty body</em></p>"}
                </div>
                """

            stages_html.append(f"""
                <div class="stage {stage_class}">
                    <div class="stage-header">
                        <span>Stage {len(stages_html) + 1}: {stage["name"]}</span>
                        <span class="{status_class}">{status_text} (HTTP {stage["status"]})</span>
                    </div>
                    <div class="request-response">
                        {request_html}
                        {response_html}
                    </div>
                </div>
            """)

        return "\n".join(stages_html)

    def _format_json(self, data: dict, title: str) -> str:
        """Format JSON as highlighted HTML."""
        if not data:
            return ""

        json_str = json.dumps(data, indent=2, ensure_ascii=False)
        # Simple syntax highlighting
        highlighted = (
            json_str.replace("true", '<span class="json-boolean">true</span>')
            .replace("false", '<span class="json-boolean">false</span>')
            .replace("null", '<span class="json-null">null</span>')
        )
        # Highlight keys (strings with quotes followed by colon)
        import re

        highlighted = re.sub(r"\"([^\"]+)\"", r'<span class="json-key">"\1"</span>:', highlighted)

        return f"""
            <h4>{title}</h4>
            <pre>{highlighted}</pre>
        """

    def _status_to_badge(self, status: int) -> str:
        """Convert HTTP status to badge class."""
        if 200 <= status < 300:
            return "get"
        elif 300 <= status < 400:
            return "get"
        elif 400 <= status < 500:
            return "post"
        else:
            return "delete"

    def _get_llm_mode(self) -> str:
        """Extract LLM mode from results."""
        for stage in self.stages:
            if stage["name"] == "Run Investigation":
                body = stage["response"].get("body") or {}
                return body.get("model_mode", "unknown")
        return "N/A"


def check_ollama(reporter: E2EReporter) -> bool:
    """Verify Ollama is reachable and has a model."""
    try:
        r = httpx.get(f"{OLLAMA_URL}/api/tags", timeout=10)
        r.raise_for_status()
        models = r.json().get("models", [])
        names = [m.get("name", "") for m in models]
        reporter.ollama_ok = True
        reporter.log("OLLAMA", f"Reachable — {len(models)} model(s): {', '.join(names)}")
        return True
    except Exception as e:
        reporter.log("OLLAMA", f"UNREACHABLE: {e}")
        return False


def check_server(reporter: E2EReporter) -> bool:
    """Verify the app server is reachable."""
    try:
        r = httpx.get(f"{BASE_URL}/api/v1/health", timeout=10)
        r.raise_for_status()
        reporter.server_ok = True
        reporter.log("SERVER", f"Healthy — {r.json()}")
        return True
    except Exception as e:
        reporter.log("SERVER", f"UNREACHABLE at {BASE_URL}: {e}")
        return False


def find_transaction_id(client: httpx.Client, reporter: E2EReporter) -> str | None:
    """Discover an uninvestigated DECLINE transaction via platform APIs (no direct DB access).

    Discovery order:
    1. E2E_TRANSACTION_ID env var (explicit override)
    2. Transaction Management API — fetch DECLINE transactions, find one not yet investigated
    """
    # Explicit override takes priority
    txn_id = os.getenv("E2E_TRANSACTION_ID")
    if txn_id:
        reporter.log("SETUP", f"Using provided transaction ID: {txn_id}")
        return txn_id

    # Auto-discover via Transaction Management API
    reporter.log("SETUP", f"Auto-discovering DECLINE transaction from TM API ({TM_BASE_URL})")
    try:
        tm_response = client.get(
            f"{TM_BASE_URL}/api/v1/transactions",
            params={"decision": "DECLINE", "limit": 20},
            timeout=10,
        )
        if tm_response.status_code != 200:
            reporter.log(
                "SETUP",
                f"TM API returned {tm_response.status_code} — set E2E_TRANSACTION_ID manually",
            )
            return None

        candidates = tm_response.json().get("items", [])
        reporter.log("SETUP", f"TM API returned {len(candidates)} DECLINE candidate(s)")

        for candidate in candidates:
            cid = candidate.get("transaction_id")
            if not cid:
                continue

            # Check if already investigated (no insights = not yet run)
            insights_resp = client.get(
                f"{API_PREFIX}/transactions/{cid}/insights",
                timeout=10,
            )
            if insights_resp.status_code == 200:
                existing = insights_resp.json().get("insights", [])
                if not existing:
                    reporter.log("SETUP", f"Found uninvestigated transaction: {cid}")
                    return cid
                # Already has insights — skip and try next

        reporter.log(
            "SETUP",
            "All DECLINE transactions already investigated — set E2E_TRANSACTION_ID manually",
        )
        return None

    except (httpx.RequestError, KeyError, ValueError) as e:
        reporter.log("SETUP", f"TM API discovery failed: {e} — set E2E_TRANSACTION_ID manually")
        return None


def run_e2e() -> bool:
    """Run the full e2e test pipeline."""
    reporter = E2EReporter()

    print("\n=== Card Fraud Ops Analyst Agent — E2E Local Test ===\n")

    # Pre-flight checks
    check_ollama(reporter)
    check_server(reporter)

    if not reporter.server_ok:
        print("\nFAIL: Server not reachable. Start with: uv run doppler-local")
        return False

    if not reporter.ollama_ok:
        print("\nWARN: Ollama not reachable — LLM reasoning will fall back to deterministic mode")

    client = httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)

    # Determine transaction ID
    txn_id = find_transaction_id(client, reporter)
    if not txn_id:
        # If no transaction ID provided, try to run with a dummy UUID
        # The server will return an error if the transaction doesn't exist
        txn_id = os.getenv("E2E_TRANSACTION_ID")
        if not txn_id:
            print("\nFAIL: No uninvestigated DECLINE transaction found. Options:")
            print(
                "  1. Set E2E_TRANSACTION_ID=<uuid> explicitly (get from TM API or Intelligence Portal)"
            )
            print("  2. Run `uv run db-load-test-data` to load fresh DECLINE transactions")
            client.close()
            return False

    reporter.transaction_id = txn_id
    print(f"\n  Transaction ID: {txn_id}\n")

    # Stage 1: Run investigation
    print("--- Stage 1: Run Investigation ---")
    start = time.perf_counter()
    try:
        url = f"{API_PREFIX}/investigations/run"
        body = {"transaction_id": txn_id, "mode": "quick"}
        r = client.post(url, json=body)
        elapsed = (time.perf_counter() - start) * 1000

        response_body = r.json() if r.status_code == 200 else None
        reporter.record_stage(
            stage_name="Run Investigation",
            status=r.status_code,
            elapsed_ms=elapsed,
            request_method="POST",
            request_url=url,
            request_body=body,
            response_status=r.status_code,
            response_body=response_body,
            response_headers=dict(r.headers),
        )

        if r.status_code == 200:
            run_id = response_body.get("run_id")
            print(f"  [RUN] OK — run_id={run_id}")
        else:
            print(f"  [RUN] FAIL — {r.status_code}: {r.text}")
            client.close()
            return False
    except Exception as e:
        reporter.record_stage(
            stage_name="Run Investigation",
            status=0,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            request_method="POST",
            request_url=f"{API_PREFIX}/investigations/run",
            request_body={"transaction_id": txn_id, "mode": "quick"},
            error=str(e),
        )
        print(f"  [RUN] ERROR: {e}")
        client.close()
        return False

    run_id = reporter.stages[0]["response"]["body"].get("run_id")

    # Stage 2: Get investigation detail
    print("\n--- Stage 2: Get Investigation Detail ---")
    start = time.perf_counter()
    try:
        url = f"{API_PREFIX}/investigations/{run_id}"
        r = client.get(url)
        elapsed = (time.perf_counter() - start) * 1000

        response_body = r.json() if r.status_code == 200 else None
        reporter.record_stage(
            stage_name="Get Investigation Detail",
            status=r.status_code,
            elapsed_ms=elapsed,
            request_method="GET",
            request_url=url,
            response_status=r.status_code,
            response_body=response_body,
            response_headers=dict(r.headers),
        )

        if r.status_code == 200:
            body = response_body
            insight = body.get("insight")
            recs = body.get("recommendations", [])
            evidence = body.get("evidence", [])
            print(
                f"  [DETAIL] OK — insight={'yes' if insight else 'none'}, recommendations={len(recs)}, evidence={len(evidence)}"
            )
        else:
            print(f"  [DETAIL] FAIL — {r.status_code}: {r.text}")
    except Exception as e:
        reporter.record_stage(
            stage_name="Get Investigation Detail",
            status=0,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            request_method="GET",
            request_url=url,
            error=str(e),
        )
        print(f"  [DETAIL] ERROR: {e}")

    # Stage 3: Get transaction insights
    print("\n--- Stage 3: Get Transaction Insights ---")
    start = time.perf_counter()
    try:
        url = f"{API_PREFIX}/transactions/{txn_id}/insights"
        r = client.get(url)
        elapsed = (time.perf_counter() - start) * 1000

        response_body = r.json() if r.status_code == 200 else None
        reporter.record_stage(
            stage_name="Get Transaction Insights",
            status=r.status_code,
            elapsed_ms=elapsed,
            request_method="GET",
            request_url=url,
            response_status=r.status_code,
            response_body=response_body,
            response_headers=dict(r.headers),
        )

        if r.status_code == 200:
            body = response_body
            insights = body.get("insights", [])
            print(f"  [INSIGHTS] OK — {len(insights)} insight(s)")
            if insights:
                first = insights[0]
                print(
                    f"  [INSIGHTS]   severity={first.get('severity')}, summary={first.get('summary', '')[:80]}"
                )
        else:
            print(f"  [INSIGHTS] FAIL — {r.status_code}: {r.text}")
    except Exception as e:
        reporter.record_stage(
            stage_name="Get Transaction Insights",
            status=0,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            request_method="GET",
            request_url=url,
            error=str(e),
        )
        print(f"  [INSIGHTS] ERROR: {e}")

    # Stage 4: List worklist recommendations
    print("\n--- Stage 4: List Worklist Recommendations ---")
    start = time.perf_counter()
    try:
        url = f"{API_PREFIX}/worklist/recommendations"
        r = client.get(url)
        elapsed = (time.perf_counter() - start) * 1000

        response_body = r.json() if r.status_code == 200 else None
        reporter.record_stage(
            stage_name="List Worklist Recommendations",
            status=r.status_code,
            elapsed_ms=elapsed,
            request_method="GET",
            request_url=url,
            response_status=r.status_code,
            response_body=response_body,
            response_headers=dict(r.headers),
        )

        if r.status_code == 200:
            body = response_body
            recs = body.get("recommendations", [])
            print(f"  [WORKLIST] OK — {len(recs)} recommendation(s)")
            rec_id = recs[0].get("recommendation_id") if recs else None
        else:
            print(f"  [WORKLIST] FAIL — {r.status_code}: {r.text}")
    except Exception as e:
        reporter.record_stage(
            stage_name="List Worklist Recommendations",
            status=0,
            elapsed_ms=(time.perf_counter() - start) * 1000,
            request_method="GET",
            request_url=url,
            error=str(e),
        )
        print(f"  [WORKLIST] ERROR: {e}")

    # Stage 5: Acknowledge a recommendation (if one exists)
    rec_id = (
        reporter.stages[3]["response"]["body"]
        .get("recommendations", [{}])[0]
        .get("recommendation_id")
        if reporter.stages[3]["response"].get("body")
        else None
    )
    if rec_id:
        print("\n--- Stage 5: Acknowledge Recommendation ---")
        start = time.perf_counter()
        try:
            url = f"{API_PREFIX}/worklist/recommendations/{rec_id}/acknowledge"
            body = {"action": "ACKNOWLEDGED", "comment": "E2E test ack"}
            r = client.post(url, json=body)
            elapsed = (time.perf_counter() - start) * 1000

            response_body = r.json() if r.status_code == 200 else None
            reporter.record_stage(
                stage_name="Acknowledge Recommendation",
                status=r.status_code,
                elapsed_ms=elapsed,
                request_method="POST",
                request_url=url,
                request_body=body,
                response_status=r.status_code,
                response_body=response_body,
                response_headers=dict(r.headers),
            )

            if r.status_code == 200:
                print(f"  [ACK] OK — recommendation {rec_id} acknowledged")
            else:
                print(f"  [ACK] FAIL — {r.status_code}: {r.text}")
        except Exception as e:
            reporter.record_stage(
                stage_name="Acknowledge Recommendation",
                status=0,
                elapsed_ms=(time.perf_counter() - start) * 1000,
                request_method="POST",
                request_url=url,
                request_body={"action": "ACKNOWLEDGED", "comment": "E2E test ack"},
                error=str(e),
            )
            print(f"  [ACK] ERROR: {e}")
    else:
        print("\n--- Stage 5: Acknowledge Recommendation (SKIPPED — no recommendations) ---")

    # Generate HTML report
    print("\n=== Generating HTML Report ===")
    REPORT_DIR.mkdir(parents=True, exist_ok=True)

    html_content = reporter.generate_html()
    with open(REPORT_FILE, "w", encoding="utf-8") as f:
        f.write(html_content)

    # Summary
    print("\n=== Results Summary ===\n")
    passed_count = sum(1 for s in reporter.stages if s["status"] == 200)
    total_count = len(reporter.stages)
    for stage, data in enumerate(reporter.stages, 1):
        status = data["status"]
        elapsed = data["elapsed_ms"]
        ok = status == 200
        marker = "PASS" if ok else "FAIL"
        print(f"  {marker}  Stage {stage}: {data['name']} - HTTP {status} ({elapsed:.0f}ms)")

    # Check LLM mode
    model_mode = reporter._get_llm_mode()
    if model_mode == "hybrid":
        print(f"\n  LLM Mode: {model_mode} (LLM reasoning active)")
    else:
        print(f"\n  LLM Mode: {model_mode} (deterministic only — check Ollama + feature flag)")

    print()
    all_ok = passed_count == total_count
    if all_ok:
        print("  ALL STAGES PASSED")
    else:
        print("  SOME STAGES FAILED — check output above")

    print(f"\n  HTML Report: {REPORT_FILE.absolute()}")

    client.close()
    return all_ok


def main() -> None:
    success = run_e2e()
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
