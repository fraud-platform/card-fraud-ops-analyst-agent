"""Run repository - CRUD for investigation runs."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.utils.clock import utc_now


class RunRepository:
    """CRUD operations for ops_agent_runs."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def create(
        self,
        mode: str,
        transaction_id: str,
        case_id: str | None = None,
        *,
        runtime_feature_flags: dict[str, bool] | None = None,
        runtime_safeguards: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Create a new run record."""
        run_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_runs
                (
                    run_id,
                    mode,
                    trigger_ref,
                    model_mode,
                    started_at,
                    status,
                    stage_durations,
                    runtime_feature_flags,
                    runtime_safeguards
                )
            VALUES
                (
                    :run_id,
                    :mode,
                    :trigger_ref,
                    'deterministic',
                    :started_at,
                    'RUNNING',
                    CAST(:stage_durations AS jsonb),
                    CAST(:runtime_feature_flags AS jsonb),
                    CAST(:runtime_safeguards AS jsonb)
                )
            RETURNING run_id, mode, trigger_ref, model_mode, started_at, status, completed_at,
                      llm_status, llm_error, llm_model, duration_ms, stage_durations, error_summary,
                      runtime_feature_flags, runtime_safeguards
        """)
        result = await self.session.execute(
            query,
            {
                "run_id": run_id,
                "mode": mode,
                "trigger_ref": f"transaction:{transaction_id}"
                + (f" case:{case_id}" if case_id else ""),
                "started_at": now,
                "stage_durations": json.dumps({}),
                "runtime_feature_flags": json.dumps(runtime_feature_flags or {}),
                "runtime_safeguards": json.dumps(runtime_safeguards or {}),
            },
        )
        return row_to_dict(result.fetchone())

    async def get(self, run_id: str) -> dict[str, Any] | None:
        """Get run by ID."""
        query = text("""
            SELECT run_id, mode, trigger_ref, model_mode, started_at, completed_at, status,
                   llm_status, llm_error, llm_model, duration_ms, stage_durations, error_summary,
                   runtime_feature_flags, runtime_safeguards
            FROM fraud_gov.ops_agent_runs
            WHERE run_id = :run_id
        """)
        result = await self.session.execute(query, {"run_id": run_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def get_by_trigger_ref(self, trigger_ref: str) -> dict[str, Any] | None:
        """Get the most recent run for a given trigger_ref."""
        query = text("""
            SELECT run_id, mode, trigger_ref, model_mode, started_at, completed_at, status,
                   llm_status, llm_error, llm_model, duration_ms, stage_durations, error_summary,
                   runtime_feature_flags, runtime_safeguards
            FROM fraud_gov.ops_agent_runs
            WHERE trigger_ref = :trigger_ref
            ORDER BY started_at DESC
            LIMIT 1
        """)
        result = await self.session.execute(query, {"trigger_ref": trigger_ref})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def complete(
        self,
        run_id: str,
        status: str,
        error_summary: str | None = None,
        *,
        model_mode: str | None = None,
        llm_status: str | None = None,
        llm_error: str | None = None,
        llm_model: str | None = None,
        duration_ms: float | None = None,
        stage_durations: dict[str, float] | None = None,
        runtime_feature_flags: dict[str, bool] | None = None,
        runtime_safeguards: dict[str, bool] | None = None,
    ) -> dict[str, Any]:
        """Mark run as completed."""
        now = utc_now()

        query = text("""
            UPDATE fraud_gov.ops_agent_runs
            SET completed_at = :completed_at,
                status = :status,
                error_summary = :error_summary,
                model_mode = COALESCE(:model_mode, model_mode),
                llm_status = COALESCE(:llm_status, llm_status),
                llm_error = COALESCE(:llm_error, llm_error),
                llm_model = COALESCE(:llm_model, llm_model),
                duration_ms = COALESCE(:duration_ms, duration_ms),
                stage_durations = COALESCE(CAST(:stage_durations AS jsonb), stage_durations),
                runtime_feature_flags = COALESCE(
                    CAST(:runtime_feature_flags AS jsonb),
                    runtime_feature_flags
                ),
                runtime_safeguards = COALESCE(
                    CAST(:runtime_safeguards AS jsonb),
                    runtime_safeguards
                )
            WHERE run_id = :run_id
            RETURNING run_id, mode, trigger_ref, model_mode, started_at, completed_at, status,
                      llm_status, llm_error, llm_model, duration_ms, stage_durations, error_summary,
                      runtime_feature_flags, runtime_safeguards
        """)
        result = await self.session.execute(
            query,
            {
                "run_id": run_id,
                "completed_at": now,
                "status": status,
                "error_summary": error_summary,
                "model_mode": model_mode,
                "llm_status": llm_status,
                "llm_error": llm_error,
                "llm_model": llm_model,
                "duration_ms": duration_ms,
                "stage_durations": (
                    json.dumps(stage_durations) if stage_durations is not None else None
                ),
                "runtime_feature_flags": (
                    json.dumps(runtime_feature_flags) if runtime_feature_flags is not None else None
                ),
                "runtime_safeguards": (
                    json.dumps(runtime_safeguards) if runtime_safeguards is not None else None
                ),
            },
        )
        return row_to_dict(result.fetchone())
