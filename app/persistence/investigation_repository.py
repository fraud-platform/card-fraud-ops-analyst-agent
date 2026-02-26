"""Investigation repository for ops_agent_investigations table."""

from __future__ import annotations

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.persistence.query_builder import build_optional_equals_where
from app.utils.clock import utc_now


class InvestigationRepository:
    """Repository for investigation records."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def create(
        self,
        investigation_id: str,
        transaction_id: str,
        mode: str,
        priority: str = "MEDIUM",
        max_steps: int = 20,
        planner_model: str | None = None,
    ) -> dict[str, Any]:
        """Create a new investigation record."""
        now = utc_now()
        query = text("""
            INSERT INTO fraud_gov.ops_agent_investigations
                (id, transaction_id, mode, status, priority, step_count, max_steps,
                 planner_model, started_at, created_at, updated_at)
            VALUES
                (:id, :txn_id, :mode, 'PENDING', :priority, 0, :max_steps,
                 :planner_model, :started_at, :created_at, :updated_at)
            RETURNING *
        """)
        result = await self._session.execute(
            query,
            {
                "id": investigation_id,
                "txn_id": transaction_id,
                "mode": mode,
                "priority": priority,
                "max_steps": max_steps,
                "planner_model": planner_model,
                "started_at": now,
                "created_at": now,
                "updated_at": now,
            },
        )
        return row_to_dict(result.fetchone())

    async def get(self, investigation_id: str) -> dict[str, Any] | None:
        """Get investigation by ID."""
        query = text("""
            SELECT * FROM fraud_gov.ops_agent_investigations
            WHERE id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        row = result.fetchone()
        return row_to_dict(row) if row else None

    async def complete(
        self,
        investigation_id: str,
        status: str,
        severity: str,
        final_confidence: float,
        step_count: int,
    ) -> dict[str, Any]:
        """Mark investigation as completed."""
        now = utc_now()
        query = text("""
            UPDATE fraud_gov.ops_agent_investigations
            SET status = :status,
                severity = :severity,
                final_confidence = :confidence,
                step_count = :step_count,
                completed_at = :completed_at,
                updated_at = :updated_at
            WHERE id = :id
            RETURNING *
        """)
        result = await self._session.execute(
            query,
            {
                "id": investigation_id,
                "status": status,
                "severity": severity,
                "confidence": final_confidence,
                "step_count": step_count,
                "completed_at": now,
                "updated_at": now,
            },
        )
        return row_to_dict(result.fetchone())

    async def update_status(
        self,
        investigation_id: str,
        status: str,
    ) -> dict[str, Any] | None:
        """Update investigation status (e.g. PENDING → IN_PROGRESS)."""
        now = utc_now()
        query = text("""
            UPDATE fraud_gov.ops_agent_investigations
            SET status = :status,
                updated_at = :updated_at
            WHERE id = :id
            RETURNING *
        """)
        result = await self._session.execute(
            query,
            {
                "id": investigation_id,
                "status": status,
                "updated_at": now,
            },
        )
        row = result.fetchone()
        return row_to_dict(row) if row else None

    async def get_active_for_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        """Get active (IN_PROGRESS) investigation for a transaction."""
        query = text("""
            SELECT * FROM fraud_gov.ops_agent_investigations
            WHERE transaction_id = :txn_id AND status = 'IN_PROGRESS'
            LIMIT 1
        """)
        result = await self._session.execute(query, {"txn_id": transaction_id})
        row = result.fetchone()
        return row_to_dict(row) if row else None

    async def list(
        self,
        limit: int = 50,
        offset: int = 0,
        status: str | None = None,
        transaction_id: str | None = None,
    ) -> list[dict[str, Any]]:
        """List investigations with optional filters."""
        where_clause, filter_params = build_optional_equals_where(
            {
                "status": status,
                "transaction_id": transaction_id,
            },
            param_aliases={"transaction_id": "txn_id"},
        )
        params: dict[str, Any] = {"limit": limit, "offset": offset, **filter_params}
        query = text(f"""
            SELECT * FROM fraud_gov.ops_agent_investigations
            WHERE {where_clause}
            ORDER BY started_at DESC
            LIMIT :limit OFFSET :offset
        """)
        result = await self._session.execute(query, params)
        return [row_to_dict(row) for row in result.fetchall()]

    async def count(
        self,
        status: str | None = None,
        transaction_id: str | None = None,
    ) -> int:
        """Count investigations with optional filters."""
        where_clause, params = build_optional_equals_where(
            {
                "status": status,
                "transaction_id": transaction_id,
            },
            param_aliases={"transaction_id": "txn_id"},
        )
        query = text(f"""
            SELECT COUNT(*) as count FROM fraud_gov.ops_agent_investigations
            WHERE {where_clause}
        """)
        result = await self._session.execute(query, params)
        row = result.fetchone()
        return row[0] if row else 0
