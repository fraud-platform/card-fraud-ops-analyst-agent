"""Create ops_agent tables in fraud_gov schema.

This script NEVER drops the fraud_gov schema.
It only creates THIS project's tables to avoid affecting other projects
that share the schema (e.g., card-fraud-rule-management, card-fraud-transaction-management).
"""

import asyncio
import logging
import os
import sys
from pathlib import Path

logger = logging.getLogger(__name__)


def _extract_statements(sql: str) -> list[str]:
    """Split SQL on ';' and strip comment-only chunks, returning executable statements."""
    statements = []
    for chunk in sql.split(";"):
        # Strip comment lines, leaving only actual SQL lines
        sql_lines = [line for line in chunk.splitlines() if not line.strip().startswith("--")]
        stmt = "\n".join(sql_lines).strip()
        if stmt:
            statements.append(stmt)
    return statements


async def setup() -> None:
    """Create ops_agent tables if they don't exist."""
    from sqlalchemy import text
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import to_asyncpg_url

    # DDL requires the admin/superuser connection (CREATE TABLE, GRANT, etc.)
    database_url = os.environ.get("DATABASE_URL_ADMIN") or os.environ.get("DATABASE_URL_APP")
    if not database_url:
        logger.error(
            "DATABASE_URL_ADMIN (or DATABASE_URL_APP) not set. "
            "Use Doppler: doppler run -- python -m scripts.setup_database"
        )
        sys.exit(1)

    database_url = to_asyncpg_url(database_url)
    engine = create_async_engine(database_url)

    migrations_dir = Path(__file__).parent.parent / "db" / "migrations"
    migration_files = sorted(migrations_dir.glob("*.sql"))

    # Run each migration file in its own transaction so a failure in one
    # file does not roll back tables created by a prior file.
    for migration_file in migration_files:
        logger.info(f"Running migration: {migration_file.name}")
        sql = migration_file.read_text()
        async with engine.begin() as conn:
            for statement in _extract_statements(sql):
                try:
                    await conn.execute(text("SAVEPOINT _migration_stmt"))
                    await conn.execute(text(statement))
                    await conn.execute(text("RELEASE SAVEPOINT _migration_stmt"))
                except Exception as e:
                    await conn.execute(text("ROLLBACK TO SAVEPOINT _migration_stmt"))
                    logger.warning(f"Statement skipped (may already exist): {e}")

    await engine.dispose()
    logger.info("Database setup complete")


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    asyncio.run(setup())
