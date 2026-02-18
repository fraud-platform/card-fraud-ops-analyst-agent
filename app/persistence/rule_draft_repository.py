"""Rule draft repository - CRUD for rule drafts."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.utils.clock import utc_now


class RuleDraftRepository:
    """CRUD operations for ops_agent_rule_drafts."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        recommendation_id: str,
        insight_id: str,
        package_version: str,
        draft_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Create a new rule draft."""
        rule_draft_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_rule_drafts
                (rule_draft_id, recommendation_id, insight_id, draft_package_version, draft_payload,
                 export_status, created_at)
            VALUES
                (:rule_draft_id, :recommendation_id, :insight_id, :draft_package_version, :draft_payload,
                 'NOT_EXPORTED', :created_at)
            RETURNING rule_draft_id, recommendation_id, insight_id, draft_package_version, draft_payload,
                      export_status, exported_to, exported_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "rule_draft_id": rule_draft_id,
                "recommendation_id": recommendation_id,
                "insight_id": insight_id,
                "draft_package_version": package_version,
                "draft_payload": json.dumps(draft_payload),
                "created_at": now,
            },
        )
        return row_to_dict(result.fetchone())

    async def update_export_status(
        self,
        rule_draft_id: str,
        export_status: str,
        exported_to: str | None = None,
    ) -> dict[str, Any]:
        """Update export status of a rule draft."""
        now = utc_now()

        query = text("""
            UPDATE fraud_gov.ops_agent_rule_drafts
            SET export_status = :export_status,
                exported_to = :exported_to,
                exported_at = :exported_at
            WHERE rule_draft_id = :rule_draft_id
            RETURNING rule_draft_id, recommendation_id, draft_package_version, draft_payload,
                      export_status, exported_to, exported_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "rule_draft_id": rule_draft_id,
                "export_status": export_status,
                "exported_to": exported_to,
                "exported_at": now if exported_to else None,
            },
        )
        return row_to_dict(result.fetchone())

    async def get(self, rule_draft_id: str) -> dict[str, Any] | None:
        """Get rule draft by ID."""
        query = text("""
            SELECT rule_draft_id, recommendation_id, draft_package_version, draft_payload,
                   export_status, exported_to, exported_at, created_at
            FROM fraud_gov.ops_agent_rule_drafts
            WHERE rule_draft_id = :rule_draft_id
        """)
        result = await self.session.execute(query, {"rule_draft_id": rule_draft_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)
