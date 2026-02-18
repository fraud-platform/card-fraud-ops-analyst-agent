"""Audit repository - append-only audit log."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.utils.clock import utc_now


class AuditRepository:
    """Append-only operations for ops_agent_audit_log."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def emit(
        self,
        entity_type: str,
        entity_id: str,
        action: str,
        performed_by: str,
        old_value: dict[str, Any] | None = None,
        new_value: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Emit an audit log entry (append-only)."""
        audit_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_audit_log
                (audit_id, entity_type, entity_id, action, performed_by,
                 old_value, new_value, created_at)
            VALUES
                (:audit_id, :entity_type, :entity_id, :action, :performed_by,
                 :old_value, :new_value, :created_at)
            RETURNING audit_id, entity_type, entity_id, action, performed_by,
                      old_value, new_value, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "audit_id": audit_id,
                "entity_type": entity_type,
                "entity_id": entity_id,
                "action": action,
                "performed_by": performed_by,
                "old_value": json.dumps(old_value) if old_value is not None else None,
                "new_value": json.dumps(new_value) if new_value is not None else None,
                "created_at": now,
            },
        )
        return row_to_dict(result.fetchone())

    async def get_by_entity(self, entity_type: str, entity_id: str) -> list[dict[str, Any]]:
        """Get audit log entries for a specific entity."""
        query = text("""
            SELECT audit_id, entity_type, entity_id, action, performed_by,
                   old_value, new_value, created_at
            FROM fraud_gov.ops_agent_audit_log
            WHERE entity_type = :entity_type AND entity_id = :entity_id
            ORDER BY created_at DESC
        """)
        result = await self.session.execute(
            query, {"entity_type": entity_type, "entity_id": entity_id}
        )
        return [row_to_dict(row) for row in result.fetchall()]
