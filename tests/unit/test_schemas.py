"""Unit tests for schemas."""

from datetime import datetime

from app.schemas.v1.common import (
    ApiError,
    ExportStatus,
    ModelMode,
    PaginatedResponse,
    RecommendationStatus,
    RecommendationType,
    RunMode,
    RunStatus,
    Severity,
)
from app.schemas.v1.health import HealthResponse, ReadyResponse
from app.schemas.v1.investigations import (
    InsightSummary,
    RecommendationPayload,
    RunRequest,
)
from app.schemas.v1.recommendations import AcknowledgeRequest


def test_severity_enum():
    assert Severity.LOW.value == "LOW"
    assert Severity.HIGH.value == "HIGH"
    assert Severity.CRITICAL.value == "CRITICAL"


def test_run_mode_enum():
    assert RunMode.QUICK.value == "quick"
    assert RunMode.DEEP.value == "deep"


def test_run_status_enum():
    assert RunStatus.SUCCESS.value == "SUCCESS"
    assert RunStatus.FAILED.value == "FAILED"


def test_recommendation_status_enum():
    assert RecommendationStatus.OPEN.value == "OPEN"
    assert RecommendationStatus.ACKNOWLEDGED.value == "ACKNOWLEDGED"
    assert RecommendationStatus.REJECTED.value == "REJECTED"


def test_recommendation_type_enum():
    assert RecommendationType.REVIEW_PRIORITY.value == "review_priority"
    assert RecommendationType.RULE_CANDIDATE.value == "rule_candidate"


def test_export_status_enum():
    assert ExportStatus.NOT_EXPORTED.value == "NOT_EXPORTED"
    assert ExportStatus.EXPORTED.value == "EXPORTED"


def test_model_mode_enum():
    assert ModelMode.DETERMINISTIC.value == "deterministic"
    assert ModelMode.HYBRID.value == "hybrid"


def test_api_error():
    error = ApiError(code="TEST", message="test error")
    assert error.code == "TEST"
    assert error.message == "test error"


def test_paginated_response():
    response = PaginatedResponse(items=[1, 2, 3], next_cursor="abc", has_more=True)
    assert len(response.items) == 3
    assert response.next_cursor == "abc"
    assert response.has_more is True


def test_health_response():
    response = HealthResponse(status="ok")
    assert response.status == "ok"


def test_ready_response():
    response = ReadyResponse(status="ready", database=True)
    assert response.status == "ready"
    assert response.database is True
    assert isinstance(response.features, dict)


def test_run_request_defaults():
    request = RunRequest(transaction_id="01234567-89ab-cdef-0123-456789abcdef")
    assert request.mode == RunMode.QUICK
    assert request.case_id is None
    assert request.include_rule_draft_preview is False


def test_run_request_full():
    request = RunRequest(
        mode=RunMode.DEEP,
        transaction_id="01234567-89ab-cdef-0123-456789abcdef",
        case_id="case-456",
        include_rule_draft_preview=True,
    )
    assert request.mode == RunMode.DEEP
    assert request.case_id == "case-456"
    assert request.include_rule_draft_preview is True


def test_insight_summary():
    summary = InsightSummary(
        insight_id="ins-123",
        severity=Severity.HIGH,
        summary="Test summary",
        generated_at=datetime.now(),
    )
    assert summary.insight_id == "ins-123"
    assert summary.severity == Severity.HIGH


def test_recommendation_payload():
    payload = RecommendationPayload(title="Test", impact="High impact")
    assert payload.title == "Test"
    assert payload.impact == "High impact"


def test_acknowledge_request_valid_actions():
    for action in [RecommendationStatus.ACKNOWLEDGED, RecommendationStatus.REJECTED]:
        request = AcknowledgeRequest(action=action)
        assert request.action == action


def test_acknowledge_request_with_comment():
    request = AcknowledgeRequest(
        action=RecommendationStatus.ACKNOWLEDGED,
        comment="Looks good",
    )
    assert request.comment == "Looks good"
