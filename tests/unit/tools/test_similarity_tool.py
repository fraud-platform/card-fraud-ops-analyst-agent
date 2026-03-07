"""Unit tests for SimilarityTool resilience paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.similarity_tool import SimilarityTool


@pytest.mark.asyncio
async def test_similarity_tool_embedding_failure_returns_skipped(state_with_context):
    """Embedding failures should fail fast so issues are visible in E2E."""
    embedding_client = AsyncMock()
    embedding_client.embed.side_effect = RuntimeError("embedding backend unavailable")
    session = AsyncMock()

    tool = SimilarityTool(embedding_client=embedding_client, session=session)
    with pytest.raises(RuntimeError, match="embedding backend unavailable"):
        await tool.execute(state_with_context)
    assert session.rollback.await_count >= 1


@pytest.mark.asyncio
async def test_similarity_tool_query_failure_returns_skipped_with_embedding_metadata(
    state_with_context,
):
    """Query failures after embedding should fail fast so issues are visible in E2E."""
    embedding_client = AsyncMock()
    embedding_client.embed.return_value = SimpleNamespace(
        embedding=[0.1, 0.2, 0.3],
        model="mxbai-embed-large",
    )
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("vector query timeout")

    tool = SimilarityTool(embedding_client=embedding_client, session=session)
    with pytest.raises(RuntimeError, match="vector query timeout"):
        await tool.execute(state_with_context)
    assert session.rollback.await_count >= 1


@pytest.mark.asyncio
async def test_similarity_tool_embedding_failure_uses_heuristic_fallback(state_with_context):
    """Embedding failure should fail fast (no heuristic SQL fallback)."""
    embedding_client = AsyncMock()
    embedding_client.embed.side_effect = RuntimeError("embedding backend unavailable")

    row = SimpleNamespace(
        _mapping={
            "transaction_id": "txn-hist-001",
            "amount": 510.0,
            "card_id": "card-001",
            "merchant_id": "merch-001",
            "decision": "DECLINE",
            "three_ds_authenticated": False,
            "is_trusted_device": False,
            "avs_match": False,
            "cvv_match": False,
            "is_tokenized": False,
            "cardholder_present": False,
            "is_known_merchant": False,
            "metadata": {},
        }
    )
    result_handle = SimpleNamespace(fetchall=lambda: [row])

    session = AsyncMock()
    session.execute = AsyncMock(return_value=result_handle)

    tool = SimilarityTool(embedding_client=embedding_client, session=session)
    with pytest.raises(RuntimeError, match="embedding backend unavailable"):
        await tool.execute(state_with_context)

    session.execute.assert_not_called()
    assert session.rollback.await_count >= 1
