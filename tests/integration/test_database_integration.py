"""Integration tests for database connectivity and schema availability."""

from __future__ import annotations

import os

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import to_asyncpg_url


def _require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL_APP", "").strip()
    if not database_url:
        pytest.skip("DATABASE_URL_APP is not configured for integration tests")
    return to_asyncpg_url(database_url)


REQUIRED_TABLES = {
    "ops_agent_investigations",
    "ops_agent_investigation_state",
    "ops_agent_tool_execution_log",
    "ops_agent_insights",
    "ops_agent_evidence",
    "ops_agent_recommendations",
    "ops_agent_rule_drafts",
    "ops_agent_audit_log",
    "ops_agent_transaction_embeddings",
}


@pytest.mark.integration
@pytest.mark.asyncio
async def test_database_connectivity() -> None:
    """Verify the configured app database is reachable."""
    database_url = _require_database_url()
    engine = create_async_engine(database_url)
    try:
        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT 1"))
            assert result.scalar() == 1
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ops_agent_tables_exist() -> None:
    """Verify all ops_agent_* tables exist in fraud_gov schema."""
    database_url = _require_database_url()
    engine = create_async_engine(database_url)

    try:
        async with engine.connect() as conn:
            query = text(
                """
                SELECT table_name
                FROM information_schema.tables
                WHERE table_schema = 'fraud_gov'
                  AND table_name LIKE 'ops_agent_%'
                """
            )
            result = await conn.execute(query)
            existing = {row[0] for row in result.fetchall()}

        missing = REQUIRED_TABLES - existing
        assert not missing, f"Missing ops_agent tables: {sorted(missing)}"
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ops_agent_investigations_columns() -> None:
    """Verify ops_agent_investigations has required columns."""
    database_url = _require_database_url()
    engine = create_async_engine(database_url)

    required_columns = {
        "id",
        "transaction_id",
        "mode",
        "status",
        "priority",
        "severity",
        "final_confidence",
        "step_count",
        "max_steps",
        "planner_model",
        "started_at",
        "completed_at",
        "duration_ms",
        "error",
        "created_at",
        "updated_at",
    }

    try:
        async with engine.connect() as conn:
            query = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'fraud_gov'
                  AND table_name = 'ops_agent_investigations'
                """
            )
            result = await conn.execute(query)
            existing = {row[0] for row in result.fetchall()}

        missing = required_columns - existing
        assert not missing, f"Missing columns in ops_agent_investigations: {sorted(missing)}"
    finally:
        await engine.dispose()


@pytest.mark.integration
@pytest.mark.asyncio
async def test_ops_agent_investigation_state_columns() -> None:
    """Verify ops_agent_investigation_state has required columns."""
    database_url = _require_database_url()
    engine = create_async_engine(database_url)

    required_columns = {
        "investigation_id",
        "state",
        "version",
        "created_at",
        "updated_at",
    }

    try:
        async with engine.connect() as conn:
            query = text(
                """
                SELECT column_name
                FROM information_schema.columns
                WHERE table_schema = 'fraud_gov'
                  AND table_name = 'ops_agent_investigation_state'
                """
            )
            result = await conn.execute(query)
            existing = {row[0] for row in result.fetchall()}

        missing = required_columns - existing
        assert not missing, f"Missing columns in ops_agent_investigation_state: {sorted(missing)}"
    finally:
        await engine.dispose()
