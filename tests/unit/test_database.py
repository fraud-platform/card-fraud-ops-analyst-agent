"""Unit tests for database module."""

from unittest.mock import AsyncMock, patch

import pytest

from app.core.database import (
    create_async_engine,
    create_session_factory,
    reset_engine,
)


def test_create_async_engine():
    from app.core.config import DatabaseConfig

    config = DatabaseConfig(
        host="localhost",
        port=5432,
        name="test_db",
        user="test_user",
    )
    engine = create_async_engine(config)
    assert engine is not None


def test_create_session_factory():
    from app.core.config import DatabaseConfig

    config = DatabaseConfig(
        host="localhost",
        port=5432,
        name="test_db",
        user="test_user",
    )
    engine = create_async_engine(config)
    factory = create_session_factory(engine)
    assert factory is not None


@pytest.mark.asyncio
async def test_get_session():
    from app.core.database import get_session

    # Test that get_session is a generator
    session_gen = get_session()
    # Should be able to get first value (async generator)
    try:
        await session_gen.__anext__()
    except StopAsyncIteration:
        pass


@pytest.mark.asyncio
async def test_reset_engine():
    with patch("app.core.database._engine") as mock_engine:
        with patch("app.core.database._session_factory"):
            mock_engine.dispose = AsyncMock()
            await reset_engine()
            mock_engine.dispose.assert_called_once()
