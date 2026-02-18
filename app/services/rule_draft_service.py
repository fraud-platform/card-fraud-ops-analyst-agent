"""Rule draft service - full implementation for Phase 2."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.rule_draft_engine import RuleDraftEngine
from app.clients.rule_management_client import RuleManagementClient
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.persistence.audit_repository import AuditRepository
from app.persistence.insight_repository import InsightRepository
from app.persistence.recommendation_repository import RecommendationRepository
from app.persistence.rule_draft_repository import RuleDraftRepository


def _build_draft_response(
    rule_draft_id: str,
    recommendation_id: str,
    package_version: str,
    export_status: str,
    exported_to: str | None,
    exported_at: str | None,
    created_at: Any,
    draft_payload: Any,
    validation_errors: list[Any] | None,
    export_error: str | None,
) -> dict[str, Any]:
    """Build a standardized rule draft response dictionary."""
    return {
        "rule_draft_id": rule_draft_id,
        "recommendation_id": recommendation_id,
        "package_version": package_version,
        "export_status": export_status,
        "exported_to": exported_to,
        "exported_at": exported_at,
        "created_at": created_at,
        "draft_payload": draft_payload,
        "validation_errors": validation_errors,
        "export_error": export_error,
    }


class RuleDraftService:
    """Service for rule drafts - full implementation."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.recommendation_repo = RecommendationRepository(session)
        self.insight_repo = InsightRepository(session)
        self.rule_draft_repo = RuleDraftRepository(session)
        self.audit_repo = AuditRepository(session)

    async def create_draft(
        self,
        recommendation_id: str,
        package_version: str,
        dry_run: bool = False,
        user_id: str = "system",
    ) -> dict[str, Any]:
        """Create rule draft from recommendation.

        Args:
            recommendation_id: ID of recommendation
            package_version: Version string for draft package
            dry_run: If True, return payload without persisting
            user_id: User performing action

        Returns:
            Dict matching RuleDraftResponse schema

        Raises:
            NotFoundError: If recommendation not found
            ValidationError: If recommendation type is not rule_candidate
            ConflictError: If recommendation is not in ACKNOWLEDGED status
        """
        recommendation = await self.recommendation_repo.get(recommendation_id)

        if recommendation is None:
            raise NotFoundError(f"Recommendation not found: {recommendation_id}")

        insight_id = recommendation.get("insight_id")
        if not insight_id:
            raise ValidationError("Recommendation has no associated insight")

        insight = await self.insight_repo.get(insight_id)
        if insight is None:
            raise NotFoundError(f"Insight not found: {insight_id}")

        evidence = await self.insight_repo.get_evidence(insight_id)

        engine = RuleDraftEngine(self.session)
        result = await engine.create_draft(
            recommendation=recommendation,
            insight=insight,
            evidence=evidence,
            package_version=package_version,
            dry_run=dry_run,
            user_id=user_id,
        )

        if dry_run:
            return _build_draft_response(
                rule_draft_id="",
                recommendation_id=recommendation_id,
                package_version=package_version,
                export_status="NOT_EXPORTED",
                exported_to=None,
                exported_at=None,
                created_at=insight.get("generated_at"),
                draft_payload=result.get("draft_payload"),
                validation_errors=result.get("validation_errors", []),
                export_error=None,
            )

        draft = result.get("draft", {})
        return _build_draft_response(
            rule_draft_id=draft.get("rule_draft_id", ""),
            recommendation_id=draft.get("recommendation_id", recommendation_id),
            package_version=draft.get("draft_package_version", package_version),
            export_status=draft.get("export_status", "NOT_EXPORTED"),
            exported_to=draft.get("exported_to"),
            exported_at=draft.get("exported_at"),
            created_at=draft.get("created_at"),
            draft_payload=draft.get("draft_payload"),
            validation_errors=result.get("validation_errors", []),
            export_error=None,
        )

    async def export_draft(
        self,
        rule_draft_id: str,
        target: str,
        target_endpoint: str,
        user_id: str = "system",
    ) -> dict[str, Any]:
        """Export rule draft to rule management.

        Args:
            rule_draft_id: ID of rule draft to export
            target: Target system (e.g., "rule-management")
            target_endpoint: Endpoint path for export
            user_id: User performing action

        Returns:
            Dict matching RuleDraftResponse schema

        Raises:
            NotFoundError: If draft not found
            ValidationError: If feature flag is disabled
            ConflictError: If draft already exported
        """
        settings = get_settings()
        if not settings.features.enable_rule_draft_export:
            raise ValidationError("Rule draft export feature is not enabled")

        draft = await self.rule_draft_repo.get(rule_draft_id)

        if draft is None:
            raise NotFoundError(f"Rule draft not found: {rule_draft_id}")

        if draft.get("export_status") not in ("NOT_EXPORTED", "FAILED"):
            raise ConflictError(f"Draft already exported with status: {draft.get('export_status')}")

        client = RuleManagementClient()
        try:
            export_result = await client.export_draft(
                endpoint=target_endpoint,
                payload=draft.get("draft_payload", {}),
            )

            if export_result.success:
                updated_draft = await self.rule_draft_repo.update_export_status(
                    rule_draft_id=rule_draft_id,
                    export_status="EXPORTED",
                    exported_to=target,
                )

                recommendation_id = draft.get("recommendation_id")
                if recommendation_id:
                    await self.recommendation_repo.update_status_with_guard(
                        recommendation_id=recommendation_id,
                        expected_status="ACKNOWLEDGED",
                        new_status="EXPORTED",
                    )

                await self.audit_repo.emit(
                    entity_type="rule_draft",
                    entity_id=rule_draft_id,
                    action="export:success",
                    performed_by=user_id,
                    new_value={
                        "target": target,
                        "endpoint": target_endpoint,
                        "response_id": export_result.response_id,
                    },
                )

                return _build_draft_response(
                    rule_draft_id=updated_draft.get("rule_draft_id", rule_draft_id),
                    recommendation_id=updated_draft.get("recommendation_id", ""),
                    package_version=updated_draft.get("draft_package_version", ""),
                    export_status=updated_draft.get("export_status", "EXPORTED"),
                    exported_to=updated_draft.get("exported_to"),
                    exported_at=updated_draft.get("exported_at"),
                    created_at=updated_draft.get("created_at"),
                    draft_payload=updated_draft.get("draft_payload"),
                    validation_errors=None,
                    export_error=None,
                )
            else:
                updated_draft = await self.rule_draft_repo.update_export_status(
                    rule_draft_id=rule_draft_id,
                    export_status="FAILED",
                )

                await self.audit_repo.emit(
                    entity_type="rule_draft",
                    entity_id=rule_draft_id,
                    action="export:failed",
                    performed_by=user_id,
                    new_value={
                        "target": target,
                        "endpoint": target_endpoint,
                        "error": export_result.error_message,
                    },
                )

                return _build_draft_response(
                    rule_draft_id=draft.get("rule_draft_id", rule_draft_id),
                    recommendation_id=draft.get("recommendation_id", ""),
                    package_version=draft.get("draft_package_version", ""),
                    export_status="FAILED",
                    exported_to=draft.get("exported_to"),
                    exported_at=draft.get("exported_at"),
                    created_at=draft.get("created_at"),
                    draft_payload=draft.get("draft_payload"),
                    validation_errors=None,
                    export_error=export_result.error_message,
                )

        finally:
            await client.close()
