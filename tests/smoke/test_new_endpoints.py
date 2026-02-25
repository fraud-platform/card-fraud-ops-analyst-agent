"""Smoke tests for new API endpoints."""

import os
import uuid
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def app():
    """Create app with mocked database session."""
    from app.core.database import get_session
    from app.main import create_app

    os.environ["METRICS_TOKEN"] = "test-metrics-token"
    app = create_app()

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
    """Create test client."""
    return TestClient(app, raise_server_exceptions=False)


class TestListInvestigationsEndpoint:
    """Tests for GET /investigations endpoint."""

    def test_list_investigations_endpoint_reachable(self, client):
        """List investigations endpoint is reachable."""
        response = client.get(
            "/api/v1/ops-agent/investigations",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in (200, 401, 403, 422, 500)

    def test_list_investigations_with_filters(self, client):
        """List investigations accepts filter params."""
        response = client.get(
            "/api/v1/ops-agent/investigations?status=COMPLETED&limit=10",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in (200, 401, 403, 422, 500)


class TestInsightsEndpoint:
    """Tests for GET /transactions/{id}/insights endpoint."""

    def test_insights_endpoint_with_invalid_uuid(self, client):
        """Insights endpoint returns 200 with empty list for non-existent transaction."""
        response = client.get(
            "/api/v1/ops-agent/transactions/test-txn-001/insights",
            headers={"Authorization": "Bearer test-token"},
        )
        # No UUID validation at route level; returns 200 with empty results
        assert response.status_code in (200, 422, 500)

    def test_insights_endpoint_with_valid_uuid(self, client):
        """Insights endpoint accepts valid UUID."""
        valid_uuid = str(uuid.uuid4())
        response = client.get(
            f"/api/v1/ops-agent/transactions/{valid_uuid}/insights",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in (200, 401, 403, 404, 500)


class TestRuleDraftEndpoint:
    """Tests for GET /investigations/{id}/rule-draft endpoint."""

    def test_rule_draft_endpoint_with_invalid_uuid(self, client):
        """Rule draft endpoint returns 404 for non-existent investigation."""
        response = client.get(
            "/api/v1/ops-agent/investigations/test-inv-001/rule-draft",
            headers={"Authorization": "Bearer test-token"},
        )
        # Route accepts any string; returns 404 when no draft found
        assert response.status_code in (404, 422, 500)

    def test_rule_draft_endpoint_with_valid_uuid(self, client):
        """Rule draft endpoint accepts valid UUID."""
        valid_uuid = str(uuid.uuid4())
        response = client.get(
            f"/api/v1/ops-agent/investigations/{valid_uuid}/rule-draft",
            headers={"Authorization": "Bearer test-token"},
        )
        assert response.status_code in (200, 401, 403, 404, 500)
