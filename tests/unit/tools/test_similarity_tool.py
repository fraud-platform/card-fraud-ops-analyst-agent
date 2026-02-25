"""Unit tests for SimilarityTool resilience paths."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest

from app.tools.similarity_tool import SimilarityTool


@pytest.mark.asyncio
async def test_similarity_tool_embedding_failure_returns_skipped(state_with_context):
    """Embedding failures should degrade gracefully without aborting investigation flow."""
    embedding_client = AsyncMock()
    embedding_client.embed.side_effect = RuntimeError("embedding backend unavailable")
    session = AsyncMock()

    tool = SimilarityTool(embedding_client=embedding_client, session=session)
    result = await tool.execute(state_with_context)

    similarity_results = result["similarity_results"]
    diagnostics = similarity_results["vector_diagnostics"]

    assert similarity_results["skipped"] is True
    assert diagnostics["reason"] == "embedding_or_similarity_failed"
    assert diagnostics["candidate_count"] == 0
    assert "unavailable" in diagnostics["error"]
    assert session.rollback.await_count == 1
    assert result["evidence"][-1]["category"] == "similarity_analysis"


@pytest.mark.asyncio
async def test_similarity_tool_query_failure_returns_skipped_with_embedding_metadata(
    state_with_context,
):
    """Query failures after embedding should preserve embedding diagnostics."""
    embedding_client = AsyncMock()
    embedding_client.embed.return_value = SimpleNamespace(
        embedding=[0.1, 0.2, 0.3],
        model="mxbai-embed-large",
    )
    session = AsyncMock()
    session.execute.side_effect = RuntimeError("vector query timeout")

    tool = SimilarityTool(embedding_client=embedding_client, session=session)
    result = await tool.execute(state_with_context)

    similarity_results = result["similarity_results"]
    diagnostics = similarity_results["vector_diagnostics"]

    assert similarity_results["skipped"] is True
    assert diagnostics["reason"] == "embedding_or_similarity_failed"
    assert diagnostics["embedding_model"] == "mxbai-embed-large"
    assert diagnostics["embedding_dimension"] == 3
    assert session.rollback.await_count == 1
