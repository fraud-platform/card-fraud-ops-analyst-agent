"""PostgreSQL state store for investigation state persistence."""

from __future__ import annotations

import json
import time
from dataclasses import asdict, is_dataclass
from datetime import date, datetime
from typing import Any
from uuid import UUID

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.metrics import ops_agent_state_store_latency_seconds


def _json_default(value: Any) -> Any:
    """Serialize dataclasses and datetime/UUID values for JSONB persistence."""
    if is_dataclass(value):
        return asdict(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, UUID):
        return str(value)
    raise TypeError(f"Object of type {type(value).__name__} is not JSON serializable")


class PostgresStateStore:
    """JSONB state persistence with optimistic versioning."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    async def save_state(
        self,
        investigation_id: str,
        state: dict[str, Any],
    ) -> int:
        """Upsert investigation state. Returns new version number."""
        start_time = time.perf_counter()
        try:
            query = text("""
                INSERT INTO fraud_gov.ops_agent_investigation_state
                    (investigation_id, state, version, created_at, updated_at)
                VALUES
                    (:id, CAST(:state AS JSONB), 1, NOW(), NOW())
                ON CONFLICT (investigation_id) DO UPDATE SET
                    state = CAST(:state AS JSONB),
                    version = ops_agent_investigation_state.version + 1,
                    updated_at = NOW()
                RETURNING version
            """)
            result = await self._session.execute(
                query,
                {
                    "id": investigation_id,
                    "state": json.dumps(state, default=_json_default),
                },
            )
            row = result.fetchone()
            return row[0] if row else 0
        finally:
            elapsed = time.perf_counter() - start_time
            ops_agent_state_store_latency_seconds.labels(operation="save").observe(elapsed)

    async def load_state(
        self,
        investigation_id: str,
    ) -> dict[str, Any] | None:
        """Load latest state for investigation."""
        start_time = time.perf_counter()
        try:
            query = text("""
                SELECT state, version
                FROM fraud_gov.ops_agent_investigation_state
                WHERE investigation_id = :id
            """)
            result = await self._session.execute(query, {"id": investigation_id})
            row = result.fetchone()
            if row is None:
                return None
            state = row[0]
            if isinstance(state, str):
                return json.loads(state)
            return state
        finally:
            elapsed = time.perf_counter() - start_time
            ops_agent_state_store_latency_seconds.labels(operation="load").observe(elapsed)

    async def get_version(self, investigation_id: str) -> int:
        """Get current state version. Returns 0 if no state exists."""
        query = text("""
            SELECT version
            FROM fraud_gov.ops_agent_investigation_state
            WHERE investigation_id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        row = result.fetchone()
        return row[0] if row else 0

    async def delete_state(self, investigation_id: str) -> bool:
        """Delete state (for cleanup/retention). Returns True if deleted."""
        query = text("""
            DELETE FROM fraud_gov.ops_agent_investigation_state
            WHERE investigation_id = :id
        """)
        result = await self._session.execute(query, {"id": investigation_id})
        return result.rowcount > 0
