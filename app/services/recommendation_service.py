"""Recommendation service - worklist and status management."""

from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ConflictError, NotFoundError, ValidationError
from app.persistence.audit_repository import AuditRepository
from app.persistence.recommendation_repository import RecommendationRepository

VALID_STATUS_TRANSITIONS = {
    "OPEN": {"ACKNOWLEDGED", "REJECTED"},
    "ACKNOWLEDGED": {"EXPORTED"},
    "REJECTED": set(),
    "EXPORTED": set(),
}


class RecommendationService:
    """Service for managing recommendations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.recommendation_repo = RecommendationRepository(session)
        self.audit_repo = AuditRepository(session)

    @staticmethod
    def _normalize_recommendation_type(rec_type: str) -> str:
        """Normalize legacy or malformed recommendation types to current enum values."""
        if not rec_type:
            return "review_priority"

        normalized = str(rec_type).strip()
        legacy_map = {
            "REVIEW": "review_priority",
            "review": "review_priority",
            "REVIEW_PRIORITY": "review_priority",
            "CASE_ACTION": "case_action",
            "RULE_CANDIDATE": "rule_candidate",
        }
        if normalized in legacy_map:
            return legacy_map[normalized]

        normalized = normalized.lower()
        if normalized in {"review_priority", "case_action", "rule_candidate"}:
            return normalized
        return "review_priority"

    async def list_worklist(
        self,
        limit: int = 50,
        cursor: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List recommendations in worklist."""
        recommendations, next_cursor = await self.recommendation_repo.list_open(
            limit=limit,
            cursor=cursor,
            severity=severity,
        )
        for recommendation in recommendations:
            recommendation["type"] = self._normalize_recommendation_type(
                recommendation.get("type", "")
            )
        return recommendations, next_cursor

    async def acknowledge(
        self,
        recommendation_id: str,
        user_id: str,
        action: str,
        comment: str | None = None,
    ) -> dict[str, Any]:
        """Acknowledge or reject a recommendation."""
        recommendation = await self.recommendation_repo.get(recommendation_id)

        if recommendation is None:
            raise NotFoundError(f"Recommendation not found: {recommendation_id}")

        if action not in ("ACKNOWLEDGED", "REJECTED"):
            raise ValidationError(f"Invalid action: {action}")

        old_status = recommendation["status"]
        new_status = action

        valid_transitions = VALID_STATUS_TRANSITIONS.get(old_status, set())
        if new_status not in valid_transitions:
            raise ConflictError(f"Invalid status transition from {old_status} to {new_status}")

        updated = await self.recommendation_repo.update_status_with_guard(
            recommendation_id=recommendation_id,
            expected_status=old_status,
            new_status=new_status,
            acknowledged_by=user_id,
        )

        if updated is None:
            raise ConflictError(
                f"Status changed concurrently for recommendation: {recommendation_id}"
            )

        await self.audit_repo.emit(
            entity_type="recommendation",
            entity_id=recommendation_id,
            action=f"status_change:{action.lower()}",
            performed_by=user_id,
            old_value={"status": old_status},
            new_value={"status": new_status, "comment": comment},
        )

        return updated
