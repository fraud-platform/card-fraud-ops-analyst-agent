"""Tool execution log repository (TDD-004 §7).

Persists tool execution records to ops_agent_tool_execution_log.
"""

from __future__ import annotations

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.utils.clock import utc_now


class ToolLogRepository:
    """CRUD for ops_agent_tool_execution_log."""

    def __init__(self, session: AsyncSession) -> None:
        self._session = session

    @staticmethod
    def _as_json_dict(value: Any) -> dict[str, Any]:
        if isinstance(value, dict):
            return value
        if isinstance(value, str):
            try:
                parsed = json.loads(value)
            except json.JSONDecodeError:
                return {}
            if isinstance(parsed, dict):
                return parsed
        return {}

    @classmethod
    def _normalize_execution_row(cls, row: dict[str, Any]) -> dict[str, Any]:
        normalized = dict(row)
        normalized["input_summary"] = cls._as_json_dict(normalized.get("input_summary"))
        normalized["output_summary"] = cls._as_json_dict(normalized.get("output_summary"))
        return normalized

    async def log_execution(
        self,
        *,
        investigation_id: str,
        tool_name: str,
        step_number: int,
        input_summary: dict[str, Any],
        output_summary: dict[str, Any],
        execution_time_ms: int,
        status: str,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        """Insert a single tool execution record."""
        row_id = str(uuid.uuid7())
        now = utc_now()

        result = await self._session.execute(
            text("""
                INSERT INTO fraud_gov.ops_agent_tool_execution_log
                    (log_id, investigation_id, tool_name, step_number,
                     input_summary, output_summary, execution_time_ms,
                     status, error_message, created_at)
                VALUES
                    (:log_id, :investigation_id, :tool_name, :step_number,
                     :input_summary, :output_summary,
                     :execution_time_ms, :status, :error_message, :created_at)
                RETURNING log_id, investigation_id, tool_name, step_number,
                          input_summary, output_summary, execution_time_ms,
                          status, error_message, created_at
            """),
            {
                "log_id": row_id,
                "investigation_id": investigation_id,
                "tool_name": tool_name,
                "step_number": step_number,
                "input_summary": json.dumps(input_summary),
                "output_summary": json.dumps(output_summary),
                "execution_time_ms": execution_time_ms,
                "status": status,
                "error_message": error_message,
                "created_at": now,
            },
        )
        row = result.fetchone()
        return self._normalize_execution_row(row_to_dict(row)) if row else {}

    async def get_executions(self, investigation_id: str) -> list[dict[str, Any]]:
        """Return all tool executions for an investigation, ordered by step."""
        result = await self._session.execute(
            text("""
                SELECT *
                FROM fraud_gov.ops_agent_tool_execution_log
                WHERE investigation_id = :investigation_id
                ORDER BY step_number ASC
            """),
            {"investigation_id": investigation_id},
        )
        return [self._normalize_execution_row(row_to_dict(r)) for r in result.fetchall()]
