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
        investigation_id: str,
        rule_name: str,
        rule_description: str,
        conditions: list[dict[str, Any]],
        thresholds: dict[str, Any],
        metadata: dict[str, Any] | None = None,
        recommendation_id: str | None = None,
    ) -> dict[str, Any]:
        """Create a new rule draft."""
        rule_draft_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_rule_drafts
                (rule_draft_id, investigation_id, recommendation_id, rule_name, rule_description,
                 conditions, thresholds, metadata, export_status, created_at)
            VALUES
                (:rule_draft_id, :investigation_id, :recommendation_id, :rule_name, :rule_description,
                 :conditions, :thresholds, :metadata, 'NOT_EXPORTED', :created_at)
            RETURNING rule_draft_id, investigation_id, recommendation_id, rule_name, rule_description,
                      conditions, thresholds, metadata, export_status, exported_to, exported_at, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "rule_draft_id": rule_draft_id,
                "investigation_id": investigation_id,
                "recommendation_id": recommendation_id,
                "rule_name": rule_name,
                "rule_description": rule_description,
                "conditions": json.dumps(conditions),
                "thresholds": json.dumps(thresholds),
                "metadata": json.dumps(metadata or {}),
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
            RETURNING rule_draft_id, investigation_id, recommendation_id, rule_name, rule_description,
                      conditions, thresholds, metadata, export_status, exported_to, exported_at, created_at
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
            SELECT rule_draft_id, investigation_id, recommendation_id, rule_name, rule_description,
                   conditions, thresholds, metadata, export_status, exported_to, exported_at, created_at
            FROM fraud_gov.ops_agent_rule_drafts
            WHERE rule_draft_id = :rule_draft_id
        """)
        result = await self.session.execute(query, {"rule_draft_id": rule_draft_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def get_by_investigation(self, investigation_id: str) -> dict[str, Any] | None:
        """Get rule draft by investigation ID."""
        query = text("""
            SELECT rule_draft_id, investigation_id, recommendation_id, rule_name, rule_description,
                   conditions, thresholds, metadata, export_status, exported_to, exported_at, created_at
            FROM fraud_gov.ops_agent_rule_drafts
            WHERE investigation_id = :investigation_id
        """)
        result = await self.session.execute(query, {"investigation_id": investigation_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)
