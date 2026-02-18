"""Truncate data from ops_agent tables only.

Keeps table structure intact. Only removes data.
This script NEVER touches other project's tables.
"""

import asyncio
import logging
import os
import sys

logger = logging.getLogger(__name__)

OPS_AGENT_TABLES = [
    "ops_agent_transaction_embeddings",
    "ops_agent_audit_log",
    "ops_agent_rule_drafts",
    "ops_agent_recommendations",
    "ops_agent_evidence",
    "ops_agent_insights",
    "ops_agent_runs",
]


async def reset_data() -> None:
    """Truncate all ops_agent tables."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import to_asyncpg_url

    # Prefer admin URL for TRUNCATE (requires superuser or table owner privilege)
    database_url = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL_APP")
    if not database_url:
        logger.error(
            "DATABASE_URL_ADMIN (or DATABASE_URL_APP) not set. "
            "Use Doppler: doppler run --config local -- python -m scripts.reset_data"
        )
        sys.exit(1)

    database_url = to_asyncpg_url(database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        for table in OPS_AGENT_TABLES:
            logger.info(f"Truncating table: fraud_gov.{table}")
            await conn.execute(text(f"TRUNCATE TABLE fraud_gov.{table} CASCADE"))

    await engine.dispose()
    logger.info("Data reset complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(reset_data())
