"""Verify ops_agent tables exist in fraud_gov schema."""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

# Agentic architecture tables
OPS_AGENT_TABLES = [
    "ops_agent_investigations",
    "ops_agent_investigation_state",
    "ops_agent_tool_execution_log",
    "ops_agent_insights",
    "ops_agent_evidence",
    "ops_agent_recommendations",
    "ops_agent_rule_drafts",
    "ops_agent_audit_log",
    "ops_agent_transaction_embeddings",
]


def _parse_bool(v: str | None) -> bool:
    if not v:
        return False
    return v.strip().lower() in {"1", "true", "yes", "on"}


async def verify() -> None:
    """Check that all ops_agent tables exist."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import to_asyncpg_url

    database_url = os.environ.get("DATABASE_URL_APP")
    if not database_url:
        logger.error(
            "DATABASE_URL_APP not set. Use Doppler: doppler run -- python -m scripts.verify_database"
        )
        sys.exit(1)

    database_url = to_asyncpg_url(database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        vector_enabled = _parse_bool(os.environ.get("VECTOR_ENABLED"))

        vector_installed = False
        try:
            ext_result = await conn.execute(
                text("SELECT 1 FROM pg_extension WHERE extname = 'vector' LIMIT 1")
            )
            vector_installed = ext_result.scalar() == 1
        except Exception as e:
            logger.warning(f"Unable to check pgvector extension status: {e}")

        result = await conn.execute(
            text(
                "SELECT table_name FROM information_schema.tables "
                "WHERE table_schema = 'public' OR table_schema = 'fraud_gov'"
            )
        )
        existing_tables = {row[0] for row in result.fetchall()}

        if vector_enabled and not vector_installed:
            logger.error(
                "VECTOR_ENABLED=true but pgvector extension is not installed in this database. "
                "Use a Postgres instance with pgvector available."
            )
            sys.exit(1)

    await engine.dispose()

    missing = []
    for table in OPS_AGENT_TABLES:
        if table in existing_tables:
            logger.info(f"  OK: {table}")
        else:
            logger.warning(f"  MISSING: {table}")
            missing.append(table)

    if missing:
        logger.error(f"Missing tables: {missing}")
        sys.exit(1)
    else:
        logger.info("All ops_agent tables verified")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(verify())
