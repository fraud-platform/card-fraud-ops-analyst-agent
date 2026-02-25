"""Recommendation repository - CRUD for recommendations."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.persistence.base import BaseCursor, row_to_dict
from app.utils.clock import utc_now

# SECURITY: Maximum recommendations returned per user to prevent resource exhaustion
# This is a soft limit; users cannot paginate beyond MAX_RECOMMENDATIONS_PER_USER items
MAX_RECOMMENDATIONS_PER_USER = 1000
VALID_SEVERITY_FILTERS = frozenset({"LOW", "MEDIUM", "HIGH", "CRITICAL"})


class RecommendationRepository:
    """CRUD operations for ops_agent_recommendations."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_recommendation(
        self,
        insight_id: str,
        recommendation_type: str,
        payload: dict[str, Any],
        idempotency_key: str,
        title: str = "Generated recommendation",
        impact: str = "Review recommended",
        investigation_id: str | None = None,
    ) -> dict[str, Any]:
        """Insert or update recommendation (idempotent)."""
        recommendation_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_recommendations
                (recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                 status, idempotency_key, created_at)
            VALUES
                (:recommendation_id, :insight_id, :investigation_id, :type, :title, :impact, :payload,
                 'OPEN', :idempotency_key, :created_at)
            ON CONFLICT (idempotency_key) DO UPDATE
            SET insight_id = EXCLUDED.insight_id,
                investigation_id = EXCLUDED.investigation_id,
                type = EXCLUDED.type,
                title = EXCLUDED.title,
                impact = EXCLUDED.impact,
                payload = EXCLUDED.payload
            RETURNING recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                      status, acknowledged_by, acknowledged_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "recommendation_id": recommendation_id,
                "insight_id": insight_id,
                "investigation_id": investigation_id,
                "type": recommendation_type,
                "title": title,
                "impact": impact,
                "payload": json.dumps(payload),
                "idempotency_key": idempotency_key,
                "created_at": now,
            },
        )
        row = result.fetchone()
        if row is None:
            select_query = text("""
                SELECT recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                       status, acknowledged_by, acknowledged_at, created_at
                FROM fraud_gov.ops_agent_recommendations
                WHERE idempotency_key = :idempotency_key
            """)
            result = await self.session.execute(select_query, {"idempotency_key": idempotency_key})
            row = result.fetchone()

        return row_to_dict(row)

    async def update_status(
        self,
        recommendation_id: str,
        status: str,
        acknowledged_by: str | None = None,
    ) -> dict[str, Any]:
        """Update recommendation status."""
        now = utc_now()

        query = text("""
            UPDATE fraud_gov.ops_agent_recommendations
            SET status = :status,
                acknowledged_by = :acknowledged_by,
                acknowledged_at = :acknowledged_at
            WHERE recommendation_id = :recommendation_id
            RETURNING recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                      status, acknowledged_by, acknowledged_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "recommendation_id": recommendation_id,
                "status": status,
                "acknowledged_by": acknowledged_by,
                "acknowledged_at": now if acknowledged_by else None,
            },
        )
        return row_to_dict(result.fetchone())

    async def list_open(
        self,
        limit: int = 50,
        cursor: str | None = None,
        severity: str | None = None,
    ) -> tuple[list[dict[str, Any]], str | None]:
        """List open recommendations with keyset pagination.

        SECURITY: Enforces MAX_RECOMMENDATIONS_PER_USER to prevent unbounded
        pagination attacks. The cursor encodes a running total count.
        """
        cursor_obj = BaseCursor.decode_optional(cursor)
        cursor_values = cursor_obj.values if cursor_obj else {}

        # SECURITY: Check page depth to prevent unbounded pagination
        total_count = cursor_values.get("_total", 0)
        if total_count >= MAX_RECOMMENDATIONS_PER_USER:
            return [], None  # No more pages allowed

        if severity is not None:
            severity = severity.strip().upper()
            if severity not in VALID_SEVERITY_FILTERS:
                raise ValidationError(
                    "Invalid severity filter",
                    details={"allowed": sorted(VALID_SEVERITY_FILTERS), "received": severity},
                )

        query_parts = [
            """
            SELECT r.recommendation_id, r.insight_id, r.investigation_id,
                   r.type, r.title, r.impact, r.payload,
                   r.status, r.acknowledged_by, r.acknowledged_at, r.created_at,
                   i.severity, i.summary
            FROM fraud_gov.ops_agent_recommendations r
            JOIN fraud_gov.ops_agent_insights i ON i.insight_id = r.insight_id
            WHERE r.status = 'OPEN'
            """
        ]

        if severity:
            query_parts.append("AND i.severity = :severity")

        has_cursor = bool(cursor_values.get("status") and cursor_values.get("created_at"))
        if has_cursor:
            query_parts.append(
                "AND (r.status, r.created_at) < (:cursor_status, :cursor_created_at)"
            )

        query_parts.append(
            """
            ORDER BY r.status ASC, r.created_at DESC
            LIMIT :limit
            """
        )
        query = text("\n".join(query_parts))

        params: dict[str, Any] = {"limit": limit + 1}
        if severity:
            params["severity"] = severity
        if has_cursor:
            params["cursor_status"] = cursor_values["status"]
            params["cursor_created_at"] = cursor_values["created_at"]

        result = await self.session.execute(query, params)
        rows = result.fetchall()

        has_more = len(rows) > limit
        if has_more:
            rows = rows[:limit]

        next_cursor = None
        returned_count = len(rows)
        new_total = total_count + returned_count

        # SECURITY: Stop paginating if we've hit the max
        if has_more and rows and new_total < MAX_RECOMMENDATIONS_PER_USER:
            last_row = rows[-1]
            next_cursor = BaseCursor(
                {
                    "status": last_row.status,
                    "created_at": str(last_row.created_at),
                    "_total": new_total,  # Track running total for depth limit
                }
            ).encode()

        return [row_to_dict(row) for row in rows], next_cursor

    async def get(self, recommendation_id: str) -> dict[str, Any] | None:
        """Get recommendation by ID."""
        query = text("""
            SELECT recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                   status, acknowledged_by, acknowledged_at, created_at
            FROM fraud_gov.ops_agent_recommendations
            WHERE recommendation_id = :recommendation_id
        """)
        result = await self.session.execute(query, {"recommendation_id": recommendation_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def update_status_with_guard(
        self,
        recommendation_id: str,
        expected_status: str,
        new_status: str,
        acknowledged_by: str | None = None,
    ) -> dict[str, Any] | None:
        """Update recommendation status with guard (atomic check).

        Uses WHERE clause to prevent race conditions - only updates if current
        status matches expected_status.

        Args:
            recommendation_id: Recommendation ID
            expected_status: Expected current status (for atomic check)
            new_status: New status to set
            acknowledged_by: User who acknowledged (for audit)

        Returns:
            Updated recommendation dict, or None if expected_status didn't match
        """
        now = utc_now()

        query = text("""
            UPDATE fraud_gov.ops_agent_recommendations
            SET status = :new_status,
                acknowledged_by = :acknowledged_by,
                acknowledged_at = :acknowledged_at
            WHERE recommendation_id = :recommendation_id
              AND status = :expected_status
            RETURNING recommendation_id, insight_id, investigation_id, type, title, impact, payload,
                      status, acknowledged_by, acknowledged_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "recommendation_id": recommendation_id,
                "expected_status": expected_status,
                "new_status": new_status,
                "acknowledged_by": acknowledged_by,
                "acknowledged_at": now if acknowledged_by else None,
            },
        )
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)
