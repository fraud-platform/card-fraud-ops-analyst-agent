"""Unit tests for rule draft service."""

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.services.rule_draft_service import RuleDraftService


@pytest.mark.asyncio
async def test_create_draft_success():
    """Test creating a rule draft successfully."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    mock_recommendation = {
        "recommendation_id": "rec-1",
        "insight_id": "insight-1",
        "type": "rule_candidate",
        "status": "ACKNOWLEDGED",
    }

    mock_insight = {
        "insight_id": "insight-1",
        "transaction_id": "txn-1",
        "generated_at": "2026-02-15T10:00:00Z",
    }

    mock_evidence = [
        {"type": "pattern", "summary": "Burst activity"},
        {"type": "similarity", "summary": "Similar transactions"},
    ]

    mock_draft_result = {
        "draft": {
            "rule_draft_id": "draft-1",
            "recommendation_id": "rec-1",
            "draft_package_version": "1.0.0",
            "export_status": "NOT_EXPORTED",
            "created_at": "2026-02-15T10:01:00Z",
            "draft_payload": {
                "rule_name": "high_velocity_burst",
                "rule_description": "Detect burst activity",
                "rule_criteria": {"velocity_6h": 5},
            },
        },
        "validation_errors": [],
    }

    service.recommendation_repo.get = AsyncMock(return_value=mock_recommendation)
    service.insight_repo.get = AsyncMock(return_value=mock_insight)
    service.insight_repo.get_evidence = AsyncMock(return_value=mock_evidence)

    # Mock RuleDraftEngine
    with (
        patch.object(service, "audit_repo", new_callable=AsyncMock),
        patch("app.services.rule_draft_service.RuleDraftEngine") as mock_engine_class,
    ):
        mock_engine = AsyncMock()
        mock_engine.create_draft = AsyncMock(return_value=mock_draft_result)
        mock_engine_class.return_value = mock_engine

        result = await service.create_draft(recommendation_id="rec-1", package_version="1.0.0")

        print("\n[RULE_DRAFT_SERVICE] Input:")
        print("  recommendation_id: rec-1")
        print("  package_version: 1.0.0")
        print("[RULE_DRAFT_SERVICE] Output:")
        print(f"  {json.dumps(result, indent=2, default=str)}")

        assert result["rule_draft_id"] == "draft-1"
        assert result["recommendation_id"] == "rec-1"
        assert result["package_version"] == "1.0.0"
        assert result["export_status"] == "NOT_EXPORTED"
        assert result["draft_payload"]["rule_name"] == "high_velocity_burst"
        mock_engine.create_draft.assert_called_once()


@pytest.mark.asyncio
async def test_create_draft_dry_run():
    """Test creating a rule draft in dry-run mode."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    mock_recommendation = {
        "recommendation_id": "rec-2",
        "insight_id": "insight-2",
        "type": "rule_candidate",
    }

    mock_insight = {
        "insight_id": "insight-2",
        "transaction_id": "txn-2",
        "generated_at": "2026-02-15T10:00:00Z",
    }

    mock_evidence = []

    mock_draft_result = {
        "draft_payload": {
            "rule_name": "test_rule",
            "rule_description": "Test description",
        },
        "validation_errors": [],
    }

    service.recommendation_repo.get = AsyncMock(return_value=mock_recommendation)
    service.insight_repo.get = AsyncMock(return_value=mock_insight)
    service.insight_repo.get_evidence = AsyncMock(return_value=mock_evidence)

    with patch("app.services.rule_draft_service.RuleDraftEngine") as mock_engine_class:
        mock_engine = AsyncMock()
        mock_engine.create_draft = AsyncMock(return_value=mock_draft_result)
        mock_engine_class.return_value = mock_engine

        result = await service.create_draft(
            recommendation_id="rec-2", package_version="1.0.0", dry_run=True
        )

        print("\n[RULE_DRAFT_SERVICE] Dry-run mode:")
        print("  Input: recommendation_id=rec-2")
        print(f"  Output: {json.dumps(result, indent=2, default=str)}")

        assert result["export_status"] == "NOT_EXPORTED"
        assert result["rule_draft_id"] == ""
        assert result["draft_payload"]["rule_name"] == "test_rule"


@pytest.mark.asyncio
async def test_create_draft_recommendation_not_found():
    """Test creating a draft when recommendation doesn't exist."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    service.recommendation_repo.get = AsyncMock(return_value=None)

    with pytest.raises(NotFoundError) as exc_info:
        await service.create_draft(recommendation_id="rec-999", package_version="1.0.0")

    print(f"\n[RULE_DRAFT_SERVICE] Expected error: {exc_info.value}")
    assert "Recommendation not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_create_draft_no_insight():
    """Test creating a draft when recommendation has no insight."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    mock_recommendation = {"recommendation_id": "rec-3", "insight_id": None}

    service.recommendation_repo.get = AsyncMock(return_value=mock_recommendation)

    with pytest.raises(ValidationError) as exc_info:
        await service.create_draft(recommendation_id="rec-3", package_version="1.0.0")

    print(f"\n[RULE_DRAFT_SERVICE] Expected error: {exc_info.value}")
    assert "Recommendation has no associated insight" in str(exc_info.value)


@pytest.mark.asyncio
async def test_export_draft_success():
    """Test exporting a draft successfully."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    mock_draft = {
        "rule_draft_id": "draft-1",
        "recommendation_id": "rec-1",
        "draft_package_version": "1.0.0",
        "export_status": "NOT_EXPORTED",
        "created_at": "2026-02-15T10:00:00Z",
        "draft_payload": {"rule_name": "test_rule"},
    }

    mock_updated_draft = {
        "rule_draft_id": "draft-1",
        "recommendation_id": "rec-1",
        "export_status": "EXPORTED",
        "exported_to": "rule-management",
        "exported_at": "2026-02-15T10:01:00Z",
        "created_at": "2026-02-15T10:00:00Z",
        "draft_package_version": "1.0.0",
        "draft_payload": {"rule_name": "test_rule"},
    }

    service.rule_draft_repo.get = AsyncMock(return_value=mock_draft)
    service.rule_draft_repo.update_export_status = AsyncMock(return_value=mock_updated_draft)
    service.recommendation_repo.update_status_with_guard = AsyncMock()
    service.audit_repo.emit = AsyncMock()

    with patch("app.services.rule_draft_service.get_settings") as mock_settings:
        mock_settings.return_value.features.enable_rule_draft_export = True

        with patch("app.services.rule_draft_service.RuleManagementClient") as mock_client_class:
            mock_client = AsyncMock()
            mock_export_result = MagicMock(success=True, response_id="rule-123", error_message=None)
            mock_client.export_draft = AsyncMock(return_value=mock_export_result)
            mock_client.close = AsyncMock()
            mock_client_class.return_value = mock_client

            result = await service.export_draft(
                rule_draft_id="draft-1",
                target="rule-management",
                target_endpoint="/api/v1/rules/drafts",
            )

            print("\n[RULE_DRAFT_SERVICE] Export:")
            print("  Input: rule_draft_id=draft-1")
            print(f"  Output: {json.dumps(result, indent=2, default=str)}")

            assert result["export_status"] == "EXPORTED"
            assert result["exported_to"] == "rule-management"
            assert result["export_error"] is None


@pytest.mark.asyncio
async def test_export_draft_feature_disabled():
    """Test exporting a draft when feature flag is disabled."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    with patch("app.services.rule_draft_service.get_settings") as mock_settings:
        mock_settings.return_value.features.enable_rule_draft_export = False

        with pytest.raises(ValidationError) as exc_info:
            await service.export_draft(
                rule_draft_id="draft-1",
                target="rule-management",
                target_endpoint="/api/v1/rules/drafts",
            )

        print(f"\n[RULE_DRAFT_SERVICE] Expected error: {exc_info.value}")
        assert "Rule draft export feature is not enabled" in str(exc_info.value)


@pytest.mark.asyncio
async def test_export_draft_not_found():
    """Test exporting a draft that doesn't exist."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    service.rule_draft_repo.get = AsyncMock(return_value=None)

    with patch("app.services.rule_draft_service.get_settings") as mock_settings:
        mock_settings.return_value.features.enable_rule_draft_export = True

        with pytest.raises(NotFoundError) as exc_info:
            await service.export_draft(
                rule_draft_id="draft-999",
                target="rule-management",
                target_endpoint="/api/v1/rules/drafts",
            )

        print(f"\n[RULE_DRAFT_SERVICE] Expected error: {exc_info.value}")
        assert "Rule draft not found" in str(exc_info.value)


@pytest.mark.asyncio
async def test_export_draft_already_exported():
    """Test exporting a draft that was already exported."""
    mock_session = AsyncMock()
    service = RuleDraftService(mock_session)

    mock_draft = {
        "rule_draft_id": "draft-1",
        "recommendation_id": "rec-1",
        "export_status": "EXPORTED",
    }

    service.rule_draft_repo.get = AsyncMock(return_value=mock_draft)

    with patch("app.services.rule_draft_service.get_settings") as mock_settings:
        mock_settings.return_value.features.enable_rule_draft_export = True

        with pytest.raises(ConflictError) as exc_info:
            await service.export_draft(
                rule_draft_id="draft-1",
                target="rule-management",
                target_endpoint="/api/v1/rules/drafts",
            )

        print(f"\n[RULE_DRAFT_SERVICE] Expected error: {exc_info.value}")
        assert "Draft already exported" in str(exc_info.value)
