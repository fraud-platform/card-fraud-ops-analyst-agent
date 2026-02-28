"""Unit tests for rule_drafts schemas."""

from datetime import datetime

from app.schemas.v1.rule_drafts import (
    CreateRequest,
    ExportRequest,
    RuleDraftResponse,
)


def test_create_request():
    req = CreateRequest(
        recommendation_id="rec-123",
        package_version="1.0",
        dry_run=False,
    )
    assert req.recommendation_id == "rec-123"
    assert req.package_version == "1.0"


def test_create_request_defaults():
    req = CreateRequest(recommendation_id="rec-123")
    assert req.dry_run is False
    assert req.package_version == "1.0"


def test_export_request():
    req = ExportRequest(
        target="rule-management",
        target_endpoint="/api/v1/rules",
    )
    assert req.target == "rule-management"


def test_rule_draft_response():
    resp = RuleDraftResponse(
        rule_draft_id="draft-123",
        recommendation_id="rec-123",
        package_version="1.0",
        export_status="NOT_EXPORTED",
        created_at=datetime.now(),
    )
    assert resp.rule_draft_id == "draft-123"
    assert resp.exported_to is None
