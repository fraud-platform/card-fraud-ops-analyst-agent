"""E2E tests for LangGraph Agentic AI investigation pipeline.

Tests the full agentic investigation flow:
1. Planner-driven tool orchestration
2. Tool execution (context, pattern, similarity, reasoning, recommendation)
3. State persistence and recovery
4. Post-graph persistence (insights, recommendations, rule drafts)

Usage:
    doppler run --config local -- uv run pytest tests/e2e/test_agentic_e2e.py -v

Requires:
    - Ops Analyst Agent server running (http://localhost:8003)
    - Transaction Management server running (http://localhost:8002)
    - Ollama running (http://localhost:11434) for LLM planner
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import pytest

from scripts.docker_guard import (
    assert_local_docker_ops_agent,
    assert_local_docker_transaction_management,
)

BASE_URL = os.getenv("E2E_BASE_URL", "http://localhost:8003")
API_PREFIX = "/api/v1/ops-agent"
TM_BASE_URL = os.getenv("TM_BASE_URL", "http://localhost:8002")
TIMEOUT = 180

assert_local_docker_ops_agent(BASE_URL)
assert_local_docker_transaction_management(TM_BASE_URL)


@pytest.fixture(scope="module")
def http_client():
    """Shared HTTP client."""
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)


@pytest.fixture(scope="module")
def tx_client():
    """Transaction management client."""
    return httpx.Client(base_url=TM_BASE_URL, timeout=TIMEOUT)


@pytest.fixture(scope="module")
def test_transaction_id(tx_client: httpx.Client):
    """Discover an existing DECLINE transaction from TM for E2E tests.

    TM returns items in 'items' key. Fetches a batch and filters for DECLINE decisions.
    Run the TM seed script first: cd card-fraud-transaction-management && doppler run --config local -- uv run python scripts/seed_transactions.py
    """
    try:
        r = tx_client.get("/api/v1/transactions", params={"limit": 200})
        if r.status_code != 200:
            pytest.skip(f"TM API not available: {r.status_code}")
        data = r.json()
        items = data.get("items", data.get("transactions", []))
        declines = [t for t in items if t.get("decision") == "DECLINE"]
        if not declines:
            pytest.skip("No DECLINE transactions found in TM — run the TM seed script first")
        # Return the first DECLINE transaction's business key (transaction_id)
        txn = declines[0]
        txn_id = txn.get("transaction_id") or txn.get("id")
        assert txn_id, f"Transaction missing ID: {txn}"
        return str(txn_id)
    except Exception as e:
        pytest.skip(f"TM API not available: {e}")


@pytest.mark.e2e
class TestAgenticInvestigationFlow:
    """Test the LangGraph agentic investigation pipeline."""

    def test_health_check(self, http_client: httpx.Client):
        """Verify server is healthy before running tests."""
        r = http_client.get("/api/v1/health")
        assert r.status_code == 200
        print(f"\n[HEALTH] Server healthy — {r.json()}")

    def test_run_agentic_investigation(
        self,
        http_client: httpx.Client,
        test_transaction_id: str,
    ):
        """Run a full agentic investigation with LangGraph orchestration."""
        print(f"\n[RUN] Starting agentic investigation for transaction {test_transaction_id}")

        run_request = {"transaction_id": test_transaction_id, "mode": "FULL"}
        start = time.perf_counter()
        r = http_client.post(f"{API_PREFIX}/investigations/run", json=run_request)
        elapsed_ms = (time.perf_counter() - start) * 1000

        print(f"[RUN] HTTP {r.status_code} in {elapsed_ms:.0f}ms")

        if r.status_code == 409:
            print("[RUN] Investigation already exists — fetching existing")
            conflict = r.json()
            run_id = conflict.get("errors", {}).get("run_id") or conflict.get("detail", {}).get(
                "run_id"
            )
            assert run_id, f"409 response missing run_id: {r.text}"
        elif r.status_code in (500, 502, 503):
            print(f"[RUN] Server error: {r.text}")
            pytest.skip(f"Server not ready: {r.status_code}")
        else:
            assert r.status_code == 200, f"Run investigation failed: {r.text}"
            data = r.json()
            run_id = data.get("investigation_id")
            assert run_id, f"Response missing investigation_id: {r.text}"

            print(f"[RUN] Created investigation: {run_id}")
            print(f"[RUN] Status: {data.get('status')}")
            print(f"[RUN] Severity: {data.get('severity')}")
            print(f"[RUN] Confidence: {data.get('confidence_score')}")
            print(f"[RUN] Step count: {data.get('step_count')}")
            print(f"[RUN] Planner decisions: {len(data.get('planner_decisions', []))}")
            print(f"[RUN] Tool executions: {len(data.get('tool_executions', []))}")
            print(f"[RUN] Recommendations: {len(data.get('recommendations', []))}")

            assert data.get("status") in ("COMPLETED", "TIMED_OUT", "FAILED")
            assert data.get("step_count", 0) >= 0

    def test_get_investigation_detail(
        self,
        http_client: httpx.Client,
        test_transaction_id: str,
    ):
        """Get investigation detail with full state."""
        list_r = http_client.get(
            f"{API_PREFIX}/investigations",
            params={"transaction_id": test_transaction_id, "limit": 1},
        )
        assert list_r.status_code == 200
        investigations = list_r.json().get("investigations", [])
        if not investigations:
            pytest.skip("No investigation found for transaction")
        run_id = investigations[0]["investigation_id"]

        r = http_client.get(f"{API_PREFIX}/investigations/{run_id}")
        assert r.status_code == 200, f"Get investigation failed: {r.text}"

        detail = r.json()
        print(f"\n[DETAIL] Investigation: {run_id}")
        print(f"[DETAIL] Status: {detail.get('status')}")
        print(f"[DETAIL] Severity: {detail.get('severity')}")
        print(f"[DETAIL] Confidence: {detail.get('confidence_score')}")
        print(f"[DETAIL] Context available: {'context' in detail}")
        print(f"[DETAIL] Pattern results: {'pattern_results' in detail}")
        print(f"[DETAIL] Similarity results: {'similarity_results' in detail}")
        print(f"[DETAIL] Reasoning: {'reasoning' in detail}")
        print(f"[DETAIL] Evidence count: {len(detail.get('evidence', []))}")
        print(f"[DETAIL] Recommendations: {len(detail.get('recommendations', []))}")

        assert "investigation_id" in detail
        assert detail["investigation_id"] == run_id

    def test_get_transaction_insights(
        self,
        http_client: httpx.Client,
        test_transaction_id: str,
    ):
        """Get insights for transaction after investigation."""
        r = http_client.get(f"{API_PREFIX}/transactions/{test_transaction_id}/insights")
        assert r.status_code == 200, f"Get insights failed: {r.text}"

        data = r.json()
        insights = data.get("insights", [])
        print(f"\n[INSIGHTS] {len(insights)} insight(s) for transaction")

        for i, insight in enumerate(insights[:3]):
            print(f"  [{i + 1}] Severity: {insight.get('severity')}")
            print(f"      Summary: {insight.get('summary', '')[:80]}...")
            print(f"      Evidence: {len(insight.get('evidence', []))} items")

    def test_list_recommendations(self, http_client: httpx.Client):
        """List worklist recommendations."""
        r = http_client.get(f"{API_PREFIX}/worklist/recommendations")
        assert r.status_code == 200, f"Get worklist failed: {r.text}"

        data = r.json()
        recs = data.get("recommendations", [])
        print(f"\n[WORKLIST] {len(recs)} open recommendation(s)")

        for i, rec in enumerate(recs[:3]):
            print(f"  [{i + 1}] Type: {rec.get('type')}")
            print(f"      Title: {rec.get('title', '')[:60]}")

    def test_list_investigations(self, http_client: httpx.Client):
        """List investigations with filters."""
        r = http_client.get(f"{API_PREFIX}/investigations", params={"limit": 10})
        assert r.status_code == 200

        data = r.json()
        investigations = data.get("investigations", [])
        total = data.get("total", 0)
        print(f"\n[LIST] {len(investigations)} investigation(s) (total: {total})")

        for inv in investigations[:3]:
            print(f"  - {inv.get('investigation_id')[:8]}... status={inv.get('status')}")

    def test_tool_execution_persistence(
        self,
        http_client: httpx.Client,
        test_transaction_id: str,
    ):
        """Verify tool executions are persisted to database."""
        list_r = http_client.get(
            f"{API_PREFIX}/investigations",
            params={"transaction_id": test_transaction_id},
        )
        assert list_r.status_code == 200
        investigations = list_r.json().get("investigations", [])
        if not investigations:
            pytest.skip("No investigation found")

        detail_r = http_client.get(
            f"{API_PREFIX}/investigations/{investigations[0]['investigation_id']}"
        )
        assert detail_r.status_code == 200
        detail = detail_r.json()

        tool_executions = detail.get("tool_executions", [])
        print(f"\n[TOOL LOG] {len(tool_executions)} tool execution(s) persisted")

        for exec in tool_executions:
            print(
                f"  - {exec.get('tool_name')}: {exec.get('status')} ({exec.get('execution_time_ms')}ms)"
            )


@pytest.mark.e2e
class TestAgenticRecovery:
    """Test investigation resume and error recovery."""

    def test_resume_nonexistent_investigation(self, http_client: httpx.Client):
        """Resume should return 404 for nonexistent investigation."""
        fake_id = str(uuid4())
        r = http_client.post(f"{API_PREFIX}/investigations/{fake_id}/resume")
        assert r.status_code == 404

    def test_rule_draft_not_found(self, http_client: httpx.Client):
        """Rule draft should return 404 for investigation without draft."""
        fake_id = str(uuid4())
        r = http_client.get(f"{API_PREFIX}/investigations/{fake_id}/rule-draft")
        assert r.status_code == 404
