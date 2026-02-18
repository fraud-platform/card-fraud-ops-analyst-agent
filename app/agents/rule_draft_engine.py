"""Rule draft engine - DB-bound adapter for rule draft generation."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.rule_draft_core import (
    assemble_draft_payload,
    validate_draft_payload,
)
from app.core.errors import ConflictError, ValidationError
from app.persistence.audit_repository import AuditRepository
from app.persistence.rule_draft_repository import RuleDraftRepository


class RuleDraftEngine:
    """Rule draft generation engine - DB-bound adapter."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.rule_draft_repo = RuleDraftRepository(session)
        self.audit_repo = AuditRepository(session)

    async def create_draft(
        self,
        recommendation: dict[str, Any],
        insight: dict[str, Any],
        evidence: list[dict[str, Any]],
        package_version: str,
        dry_run: bool,
        user_id: str,
    ) -> dict[str, Any]:
        """Create rule draft from recommendation.

        Args:
            recommendation: Recommendation dict
            insight: Insight dict
            evidence: List of evidence dicts
            package_version: Package version string
            dry_run: If True, return payload without persisting
            user_id: User performing the action

        Returns:
            Dict with draft data

        Raises:
            NotFoundError: If recommendation not found
            ValidationError: If recommendation type is not rule_candidate
            ConflictError: If recommendation is not in ACKNOWLEDGED status
        """
        rec_type = recommendation.get("type")
        if rec_type != "rule_candidate":
            raise ValidationError(
                f"Only rule_candidate recommendations can produce drafts, got: {rec_type}"
            )

        if recommendation.get("status") != "ACKNOWLEDGED":
            raise ConflictError(
                f"Recommendation must be ACKNOWLEDGED to create draft, got status: {recommendation.get('status')}"
            )

        payload = assemble_draft_payload(recommendation, insight, evidence)
        validation_errors = validate_draft_payload(payload)

        if validation_errors:
            raise ValidationError(f"Draft payload validation failed: {validation_errors}")

        draft_data = {
            "rule_name": payload.rule_name,
            "rule_description": payload.rule_description,
            "conditions": [vars(c) for c in payload.conditions],
            "thresholds": dict(payload.thresholds),
            "metadata": dict(payload.metadata),
            "package_version": package_version,
        }

        if dry_run:
            await self.audit_repo.emit(
                entity_type="rule_draft",
                entity_id="dry-run",
                action="validated",
                performed_by=user_id,
                new_value=draft_data,
            )
            return {
                "draft_payload": draft_data,
                "validation_errors": [],
                "dry_run": True,
            }

        rec_id = recommendation.get("recommendation_id")
        ins_id = insight.get("insight_id")
        if not rec_id or not ins_id:
            raise ValidationError("Recommendation or insight missing required ID")

        draft = await self.rule_draft_repo.create(
            recommendation_id=rec_id,
            insight_id=ins_id,
            package_version=package_version,
            draft_payload=draft_data,
        )

        await self.audit_repo.emit(
            entity_type="rule_draft",
            entity_id=draft["rule_draft_id"],
            action="created",
            performed_by=user_id,
            new_value=draft_data,
        )

        return {
            "draft": draft,
            "validation_errors": [],
            "dry_run": False,
        }
