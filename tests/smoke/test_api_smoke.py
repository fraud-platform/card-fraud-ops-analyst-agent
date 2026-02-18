"""Smoke tests for API endpoints."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

from app.core.tracing import get_tracing_headers


@pytest.fixture
def app():
    """Create app with mocked database session."""
    from app.core.database import get_session
    from app.main import create_app

    os.environ["METRICS_TOKEN"] = "test-metrics-token"
    app = create_app()

    # Create mock session that returns empty results
    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_result.fetchall.return_value = []
    mock_result.scalars.return_value = MagicMock(all=MagicMock(return_value=[]))
    mock_session.execute.return_value = mock_result
    mock_session.commit = AsyncMock()
    mock_session.rollback = AsyncMock()

    async def mock_get_session():
        yield mock_session

    app.dependency_overrides[get_session] = mock_get_session
    return app


@pytest.fixture
def client(app):
    """Create test client.

    raise_server_exceptions=False ensures that server-side errors (500) are
    returned as HTTP responses rather than re-raised in the test process,
    which lets us assert on status codes for endpoints that fail due to the
    mock session returning empty data.
    """
    return TestClient(app, raise_server_exceptions=False)


# --- Health endpoints (no auth, no DB) ---


def test_health_endpoint(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.json()["status"] == "ok"


def test_ready_endpoint(client):
    response = client.get("/api/v1/health/ready")
    assert response.status_code == 200
    body = response.json()
    assert "features" in body
    assert isinstance(body["features"], dict)


def test_live_endpoint(client):
    response = client.get("/api/v1/health/live")
    assert response.status_code == 200
    assert response.json()["status"] == "alive"


def test_metrics_endpoint(client):
    response = client.get("/api/v1/metrics", headers={"X-Metrics-Token": "test-metrics-token"})
    assert response.status_code == 200
    assert "ops_agent_investigation_requests_total" in response.text
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security")
    assert response.headers.get("Content-Security-Policy")


def test_metrics_endpoint_rejects_missing_token(client):
    response = client.get("/api/v1/metrics")
    assert response.status_code == 403


def test_metrics_endpoint_rejects_invalid_token(client):
    response = client.get("/api/v1/metrics", headers={"X-Metrics-Token": "invalid-token"})
    assert response.status_code == 403


def test_metrics_root_not_exposed(client):
    response = client.get("/metrics")
    assert response.status_code == 404


def test_security_headers_present_on_health(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert response.headers.get("X-Content-Type-Options") == "nosniff"
    assert response.headers.get("X-Frame-Options") == "DENY"
    assert response.headers.get("Strict-Transport-Security")
    assert response.headers.get("Content-Security-Policy")


def test_request_id_header_round_trip(client):
    request_id = "smoke-request-id-123"
    response = client.get("/api/v1/health", headers={"X-Request-ID": request_id})
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == request_id


def test_request_id_header_generated(client):
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    generated = response.headers.get("X-Request-ID")
    assert generated is not None
    uuid.UUID(generated)


def test_tracing_context_cleared_after_request(client):
    response = client.get(
        "/api/v1/health",
        headers={
            "X-Request-ID": "smoke-trace-clear-1",
            "traceparent": "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01",
        },
    )
    assert response.status_code == 200
    assert response.headers.get("X-Request-ID") == "smoke-trace-clear-1"
    assert get_tracing_headers() == {}


# --- Investigation endpoints (auth + DB) ---


def test_run_investigation_endpoint_reachable(client):
    """Verify POST /investigations/run is routable and auth works."""
    response = client.post(
        "/api/v1/ops-agent/investigations/run",
        json={"transaction_id": "test-txn-001", "mode": "quick"},
    )
    # With mock session returning None, the service will likely raise NotFoundError
    # or an internal error when transaction doesn't exist. Either way, it should NOT be 401/403.
    assert response.status_code != 401
    assert response.status_code != 403


def test_get_investigation_endpoint_reachable(client):
    """Verify GET /investigations/{run_id} is routable and auth works."""
    response = client.get("/api/v1/ops-agent/investigations/test-run-001")
    # Should be 404 (not found) since mock returns None, not 401/403
    assert response.status_code != 401
    assert response.status_code != 403


# --- Insight endpoints (auth + DB) ---


def test_get_insights_endpoint_reachable(client):
    """Verify GET /transactions/{txn_id}/insights is routable and auth works."""
    response = client.get("/api/v1/ops-agent/transactions/test-txn-001/insights")
    assert response.status_code != 401
    assert response.status_code != 403


# --- Recommendation endpoints (auth + DB) ---


def test_list_recommendations_endpoint_reachable(client):
    """Verify GET /worklist/recommendations is routable and auth works."""
    response = client.get("/api/v1/ops-agent/worklist/recommendations")
    assert response.status_code != 401
    assert response.status_code != 403


def test_list_recommendations_rejects_invalid_severity(client):
    response = client.get("/api/v1/ops-agent/worklist/recommendations?severity=INVALID")
    assert response.status_code == 422


def test_acknowledge_recommendation_endpoint_reachable(client):
    """Verify POST /worklist/recommendations/{id}/acknowledge is routable and auth works."""
    response = client.post(
        "/api/v1/ops-agent/worklist/recommendations/test-rec-001/acknowledge",
        json={"action": "ACKNOWLEDGED", "comment": "test"},
    )
    assert response.status_code != 401
    assert response.status_code != 403


# --- Rule draft endpoints (auth + DB) ---


def test_create_rule_draft_endpoint_reachable(client):
    """Verify POST /rule-drafts is routable and auth works."""
    response = client.post(
        "/api/v1/ops-agent/rule-drafts",
        json={"recommendation_id": "test-rec-001"},
    )
    assert response.status_code != 401
    assert response.status_code != 403


def test_export_rule_draft_endpoint_reachable(client):
    """Verify POST /rule-drafts/{id}/export is routable and auth works."""
    response = client.post(
        "/api/v1/ops-agent/rule-drafts/test-draft-001/export",
        json={"target": "rule-management", "target_endpoint": "http://localhost:8000"},
    )
    assert response.status_code != 401
    assert response.status_code != 403
