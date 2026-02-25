"""Full E2E test with HTML report and request/response logging.

Usage:
    doppler run --project card-fraud-ops-analyst-agent --config local -- \
        python -m pytest tests/e2e/test_e2e_full_pipeline.py --html=htmlcov/e2e.html --self-contained-html -v

Requires:
    - Ops Analyst Agent server running (http://localhost:8003)
    - Transaction Management server running (http://localhost:8002)
    - Ollama running (http://localhost:11434)
    - E2E_TRANSACTION_ID set to a valid transaction UUID
"""

from __future__ import annotations

import os
import time
from uuid import uuid4

import httpx
import pytest

from scripts.docker_guard import assert_local_docker_ops_agent

BASE_URL = "http://localhost:8003"
API_PREFIX = "/api/v1/ops-agent"
TX_MGMT_URL = "http://localhost:8002/api/v1"
TIMEOUT = 180

assert_local_docker_ops_agent(BASE_URL)


@pytest.fixture(scope="session")
def transaction_id() -> str:
    """Get transaction ID from environment."""
    txn_id = os.getenv("E2E_TRANSACTION_ID")
    if not txn_id:
        pytest.skip("E2E_TRANSACTION_ID not set")
    return txn_id


@pytest.fixture(scope="session")
def http_client():
    """Shared HTTP client."""
    return httpx.Client(base_url=BASE_URL, timeout=TIMEOUT)


@pytest.fixture(scope="session")
def tx_mgmt_client():
    """Transaction management client."""
    return httpx.Client(base_url=TX_MGMT_URL, timeout=TIMEOUT)


@pytest.mark.e2e
def test_e2e_full_pipeline(
    transaction_id: str,
    http_client: httpx.Client,
    tx_mgmt_client: httpx.Client,
):
    """Run full E2E pipeline with request/response logging."""

    # Pre-flight: Check Ollama
    try:
        r = http_client.get("http://localhost:11434/api/tags")
        r.raise_for_status()
        models = r.json().get("models", [])
        print(f"\n[OLLAMA] Reachable — {len(models)} model(s)")
    except Exception as e:
        print(f"\n[OLLAMA] UNREACHABLE: {e}")

    # Pre-flight: Check server health
    r = http_client.get(f"{BASE_URL}/api/v1/health")
    r.raise_for_status()
    print(f"[SERVER] Healthy — {r.json()}")

    # Pre-flight: Verify transaction exists
    r = tx_mgmt_client.get(f"/transactions/{transaction_id}")
    r.raise_for_status()
    print(f"\n[SETUP] Transaction ID: {transaction_id}")

    # Stage 1: Run Investigation
    print("\n--- Stage 1: Run Investigation ---")
    case_id = f"e2e-full-{int(time.time() * 1000)}-{uuid4().hex[:8]}"
    run_request = {"transaction_id": transaction_id, "mode": "quick", "case_id": case_id}
    start = time.perf_counter()
    r = http_client.post(f"{API_PREFIX}/investigations/run", json=run_request)
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[RUN] ({elapsed:.0f}ms) HTTP {r.status_code}")
    if r.status_code == 409:
        conflict_payload = r.json()
        errors = conflict_payload.get("errors", {})
        detail = conflict_payload.get("detail", {})
        run_id = (errors.get("run_id") if isinstance(errors, dict) else None) or (
            detail.get("run_id") if isinstance(detail, dict) else None
        )
        assert run_id, f"Run returned 409 but no run_id in response: {r.text}"
        model_mode = "agentic"
        print(f"[RUN] Reused existing run - run_id={run_id}, model_mode={model_mode}")
    else:
        assert r.status_code == 200, f"Run investigation failed: {r.text}"
        run_data = r.json()
        run_id = run_data["investigation_id"]
        model_mode = run_data.get("model_mode", "unknown")
        print(f"[RUN] OK - investigation_id={run_id}, model_mode={model_mode}")
    print(f"Request: POST {API_PREFIX}/investigations/run")
    print(f"Request Body: {run_request}")
    print(f"Response: {r.json()}")

    # Stage 2: Get Investigation Detail
    print("\n--- Stage 2: Get Investigation Detail ---")
    start = time.perf_counter()
    r = http_client.get(f"{API_PREFIX}/investigations/{run_id}")
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[DETAIL] ({elapsed:.0f}ms) HTTP {r.status_code}")
    assert r.status_code == 200, f"Get investigation failed: {r.text}"
    detail = r.json()
    insight = detail.get("insight")
    recs = detail.get("recommendations", [])
    evidence = detail.get("evidence", [])
    print(
        f"[DETAIL] OK — insight={'yes' if insight else 'none'}, recommendations={len(recs)}, evidence={len(evidence)}"
    )
    print(f"Request: GET {API_PREFIX}/investigations/{run_id}")
    print(f"Response: {r.json()}")

    # Stage 3: Get Transaction Insights
    print("\n--- Stage 3: Get Transaction Insights ---")
    start = time.perf_counter()
    r = http_client.get(f"{API_PREFIX}/transactions/{transaction_id}/insights")
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[INSIGHTS] ({elapsed:.0f}ms) HTTP {r.status_code}")
    assert r.status_code == 200, f"Get insights failed: {r.text}"
    insights_data = r.json()
    insights = insights_data.get("insights", [])
    print(f"[INSIGHTS] OK — {len(insights)} insight(s)")
    print(f"Request: GET {API_PREFIX}/transactions/{transaction_id}/insights")
    print(f"Response: {r.json()}")
    if insights:
        first = insights[0]
        print(
            f"[INSIGHTS] severity={first.get('severity')}, summary={first.get('summary', '')[:80]}"
        )

    # Stage 4: List Worklist Recommendations
    print("\n--- Stage 4: List Worklist Recommendations ---")
    start = time.perf_counter()
    r = http_client.get(f"{API_PREFIX}/worklist/recommendations")
    elapsed = (time.perf_counter() - start) * 1000
    print(f"[WORKLIST] ({elapsed:.0f}ms) HTTP {r.status_code}")
    assert r.status_code == 200, f"Get worklist failed: {r.text}"
    worklist = r.json()
    recs = worklist.get("recommendations", [])
    print(f"[WORKLIST] OK — {len(recs)} recommendation(s)")
    print(f"Request: GET {API_PREFIX}/worklist/recommendations")
    print(f"Response: {r.json()}")
    rec_id = recs[0].get("recommendation_id") if recs else None

    # Stage 5: Acknowledge Recommendation
    if rec_id:
        print("\n--- Stage 5: Acknowledge Recommendation ---")
        start = time.perf_counter()
        ack_body = {"action": "ACKNOWLEDGED", "comment": "E2E test ack"}
        r = http_client.post(
            f"{API_PREFIX}/worklist/recommendations/{rec_id}/acknowledge",
            json=ack_body,
        )
        elapsed = (time.perf_counter() - start) * 1000
        print(f"[ACK] ({elapsed:.0f}ms) HTTP {r.status_code}")
        assert r.status_code == 200, f"Acknowledge failed: {r.text}"
        print(f"[ACK] OK — recommendation {rec_id} acknowledged")
        print(f"Request: POST {API_PREFIX}/worklist/recommendations/{rec_id}/acknowledge")
        print(f"Request Body: {ack_body}")
        print(f"Response: {r.json()}")
    else:
        print("\n--- Stage 5: Acknowledge Recommendation (SKIPPED — no recommendations)")

    print("\n=== ALL STAGES PASSED ===")
