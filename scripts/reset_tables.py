"""Drop and recreate ONLY ops_agent tables.

WARNING: This drops all data in ops_agent_* tables.
This script NEVER drops the fraud_gov schema or any other project's tables.
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)

# Agentic architecture tables (in dependency order for drops)
OPS_AGENT_TABLES = [
    # Drop in reverse dependency order
    "ops_agent_tool_execution_log",
    "ops_agent_investigation_state",
    "ops_agent_audit_log",
    "ops_agent_rule_drafts",
    "ops_agent_recommendations",
    "ops_agent_evidence",
    "ops_agent_insights",
    "ops_agent_transaction_embeddings",
    "ops_agent_investigations",
]


async def reset() -> None:
    """Drop and recreate ops_agent tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import to_asyncpg_url

    # Prefer admin URL for DDL; fall back to app URL
    database_url = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL_APP")
    if not database_url:
        logger.error(
            "DATABASE_URL_ADMIN or DATABASE_URL_APP not set. "
            "Use Doppler: doppler run -- python -m scripts.reset_tables"
        )
        sys.exit(1)

    database_url = to_asyncpg_url(database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        # Drop in reverse dependency order (with schema prefix)
        for table in OPS_AGENT_TABLES:
            logger.info(f"Dropping table: fraud_gov.{table}")
            await conn.execute(text(f"DROP TABLE IF EXISTS fraud_gov.{table} CASCADE"))

    # Recreate using migrations — one transaction per file
    migrations_dir = Path(__file__).parent.parent / "db" / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    for migration_file in migration_files:
        logger.info(f"Running migration: {migration_file.name}")
        sql = migration_file.read_text()
        statements = _extract_statements(sql)
        async with engine.begin() as conn:
            for statement in statements:
                await conn.execute(text("SAVEPOINT sp"))
                try:
                    await conn.execute(text(statement))
                    await conn.execute(text("RELEASE SAVEPOINT sp"))
                except Exception as e:
                    logger.warning(f"Statement skipped: {e}")
                    await conn.execute(text("ROLLBACK TO SAVEPOINT sp"))
        logger.info(f"Completed migration: {migration_file.name}")

    await engine.dispose()
    logger.info("Tables reset complete")


def _extract_statements(sql: str) -> list[str]:
    """Extract SQL statements, handling comments and multi-line blocks."""
    statements = []
    for raw in sql.split(";"):
        # Strip leading comment-only lines
        lines = []
        for line in raw.split("\n"):
            stripped = line.strip()
            if stripped and not stripped.startswith("--"):
                lines.append(line)
        stmt = "\n".join(lines).strip()
        if stmt:
            statements.append(stmt)
    return statements


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(reset())
