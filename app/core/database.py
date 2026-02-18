"""Database connection and session management."""

import logging
from collections.abc import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as sqlalchemy_create_async_engine,
)
from sqlalchemy.orm import declarative_base

from app.core.config import DatabaseConfig

logger = logging.getLogger(__name__)

Base = declarative_base()

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


def create_async_engine(config: DatabaseConfig) -> AsyncEngine:
    """Create async database engine."""
    engine = sqlalchemy_create_async_engine(
        config.async_url,
        echo=config.echo,
        pool_size=config.pool_size,
        max_overflow=config.max_overflow,
        pool_timeout=config.pool_timeout,
        pool_recycle=config.pool_recycle,
        pool_pre_ping=True,
        connect_args={
            # SECURITY: Statement timeout prevents runaway queries (30 seconds)
            "server_settings": {"timezone": "UTC", "statement_timeout": "30000"},
        },
    )
    logger.info(
        "Database engine created",
        extra={
            "host": config.host,
            "port": config.port,
            "database": config.name,
        },
    )
    return engine


def create_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Create async session factory."""
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
        autocommit=False,
        autoflush=False,
    )


def get_engine() -> AsyncEngine:
    """Get or create the global database engine."""
    global _engine
    if _engine is None:
        from app.core.config import get_settings

        settings = get_settings()
        _engine = create_async_engine(settings.database)
    return _engine


def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Get or create the global session factory."""
    global _session_factory
    if _session_factory is None:
        _session_factory = create_session_factory(get_engine())
    return _session_factory


async def reset_engine() -> None:
    """Reset the database engine and session factory."""
    global _engine, _session_factory
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _session_factory = None


async def get_session() -> AsyncGenerator[AsyncSession]:
    """Get database session as async context manager."""
    factory = get_session_factory()
    async with factory() as session:
        try:
            yield session
            await session.commit()
        except Exception:
            await session.rollback()
            raise
