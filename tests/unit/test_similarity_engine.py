"""Unit tests for similarity engine adapter."""

import json
from datetime import UTC, datetime
from unittest.mock import AsyncMock

import pytest

from app.agents.similarity_engine import SimilarityEngine
from app.clients.embedding_client import EmbeddingResponse
from app.core.config import reload_settings
from app.core.errors import DependencyError


@pytest.mark.asyncio
async def test_similarity_engine_analyze(monkeypatch: pytest.MonkeyPatch):
    """Test similarity engine analysis."""
    monkeypatch.setenv("VECTOR_ENABLED", "false")
    reload_settings()
    mock_session = AsyncMock()
    engine = SimilarityEngine(mock_session)

    mock_context = {
        "transaction": {
            "transaction_id": "txn-123",
            "amount": 100.0,
            "card_id": "card-1",
            "merchant_id": "merchant-1",
        }
    }

    result = await engine.analyze(mock_context)

    print("\n[SIMILARITY_ENGINE] Input context:")
    print(f"  {json.dumps(mock_context, indent=2, default=str)}")
    print("[SIMILARITY_ENGINE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    assert "similarity_result" in result
    # similarity_result is a SimilarityResult dataclass
    assert result["similarity_result"].overall_score == 0.0  # Stub implementation
    assert len(result["similarity_result"].matches) == 0
    assert result["vector_feature_enabled"] is False
    assert result["vector_stage_executed"] is False
    assert result["vector_status"] == "disabled"


@pytest.mark.asyncio
async def test_similarity_engine_analyze_stub(monkeypatch: pytest.MonkeyPatch):
    """Test similarity engine stub returns zero score."""
    monkeypatch.setenv("VECTOR_ENABLED", "false")
    reload_settings()
    mock_session = AsyncMock()
    engine = SimilarityEngine(mock_session)

    mock_context = {"transaction": {"transaction_id": "txn-999", "amount": 50.0}}

    result = await engine.analyze(mock_context)

    print("\n[SIMILARITY_ENGINE] Stub implementation")
    print("[SIMILARITY_ENGINE] Output:")
    print(f"  {json.dumps(result, indent=2, default=str)}")

    # Stub returns zero score
    assert result["similarity_result"].overall_score == 0.0
    assert len(result["similarity_result"].matches) == 0
    assert result["vector_feature_enabled"] is False
    assert result["vector_stage_executed"] is False
    assert result["vector_status"] == "disabled"


@pytest.mark.asyncio
async def test_similarity_engine_analyze_vector_enabled(monkeypatch: pytest.MonkeyPatch):
    """Vector-enabled path uses embedding + DB matches."""

    monkeypatch.setenv("VECTOR_ENABLED", "true")
    monkeypatch.setenv("VECTOR_API_BASE", "http://example.invalid")
    monkeypatch.setenv("VECTOR_MODEL_NAME", "mxbai-embed-large")
    monkeypatch.setenv("VECTOR_DIMENSION", "3")
    reload_settings()

    class _Result:
        def __init__(self, rows: list[object]):
            self._rows = rows

        def fetchall(self) -> list[object]:
            return list(self._rows)

    mock_session = AsyncMock()

    async def _execute_side_effect(query, params):
        sql = str(query)
        if "INSERT INTO fraud_gov.ops_agent_transaction_embeddings" in sql:
            return _Result([])
        if "FROM fraud_gov.ops_agent_transaction_embeddings" in sql:
            return _Result(
                [
                    type(
                        "Row",
                        (),
                        {
                            "transaction_id": "txn-sim-1",
                            "amount": 95.0,
                            "merchant_id": "m1",
                            "card_id": "c1",
                            "transaction_timestamp": datetime.now(UTC),
                            "similarity_score": 0.7,
                        },
                    )()
                ]
            )
        # Attribute search
        return _Result(
            [
                type(
                    "Row",
                    (),
                    {
                        "transaction_id": "txn-sim-1",
                        "amount": 95.0,
                        "merchant_id": "m1",
                        "card_id": "c1",
                        "transaction_timestamp": datetime.now(UTC),
                        "similarity_score": 0.8,
                    },
                )(),
                type(
                    "Row",
                    (),
                    {
                        "transaction_id": "txn-sim-2",
                        "amount": 50.0,
                        "merchant_id": "m2",
                        "card_id": "c1",
                        "transaction_timestamp": datetime.now(UTC),
                        "similarity_score": 0.4,
                    },
                )(),
            ]
        )

    mock_session.execute = AsyncMock(side_effect=_execute_side_effect)

    engine = SimilarityEngine(mock_session)
    engine._embedding_client.embed = AsyncMock(
        return_value=EmbeddingResponse(embedding=[0.1, 0.2, 0.3], model="mxbai-embed-large")
    )

    mock_context = {
        "transaction": {
            "id": "00000000-0000-0000-0000-000000000001",
            "transaction_id": "txn-123",
            "amount": 100.0,
            "currency": "USD",
            "card_id": "c1",
            "merchant_id": "m1",
            "transaction_timestamp": datetime.now(UTC),
        }
    }

    result = await engine.analyze(mock_context)

    assert "similarity_result" in result
    sim = result["similarity_result"]
    assert sim.overall_score > 0.0
    assert len(sim.matches) == 2
    assert result["vector_feature_enabled"] is True
    assert result["vector_stage_executed"] is True
    assert result["vector_status"] == "ok"
    assert result["vector_error"] is None
    # txn-sim-1 appears in both result sets; higher attribute score should win.
    assert sim.matches[0].match_id == "txn-sim-1"

    # Avoid leaking env-driven settings into other tests.
    monkeypatch.delenv("VECTOR_ENABLED", raising=False)
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.delenv("VECTOR_MODEL_NAME", raising=False)
    monkeypatch.delenv("VECTOR_DIMENSION", raising=False)
    reload_settings()


@pytest.mark.asyncio
async def test_similarity_engine_vector_enabled_embedding_failure_raises_dependency_error(
    monkeypatch: pytest.MonkeyPatch,
):
    """When VECTOR_ENABLED=true, embedding failures fail closed (no silent fallback)."""

    monkeypatch.setenv("VECTOR_ENABLED", "true")
    monkeypatch.setenv("VECTOR_API_BASE", "http://example.invalid")
    monkeypatch.setenv("VECTOR_MODEL_NAME", "mxbai-embed-large")
    monkeypatch.setenv("VECTOR_DIMENSION", "3")
    reload_settings()

    mock_session = AsyncMock()
    engine = SimilarityEngine(mock_session)
    engine._embedding_client.embed = AsyncMock(side_effect=RuntimeError("embedding unavailable"))

    mock_context = {
        "transaction": {
            "id": "00000000-0000-0000-0000-000000000001",
            "transaction_id": "txn-123",
            "amount": 100.0,
            "currency": "USD",
            "card_id": "c1",
            "merchant_id": "m1",
            "transaction_timestamp": datetime.now(UTC),
        }
    }

    with pytest.raises(DependencyError, match="Vector similarity unavailable"):
        await engine.analyze(mock_context)

    monkeypatch.delenv("VECTOR_ENABLED", raising=False)
    monkeypatch.delenv("VECTOR_API_BASE", raising=False)
    monkeypatch.delenv("VECTOR_MODEL_NAME", raising=False)
    monkeypatch.delenv("VECTOR_DIMENSION", raising=False)
    reload_settings()


def test_counter_evidence_flags_basic():
    """Test basic counter-evidence flag extraction."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "three_ds_authenticated": True,
            "is_trusted_device": True,
        }
    )
    assert flags["three_ds_authenticated"] is True
    assert flags["is_trusted_device"] is True


def test_counter_evidence_flags_alternate_keys():
    """Test alternate key names for counter-evidence."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "3ds_verified": True,
            "device_trusted": True,
            "avs_match": True,
            "cvv_match": True,
            "is_tokenized": True,
            "is_recurring_customer": True,
            "cardholder_present": True,
            "is_known_merchant": True,
        }
    )
    assert flags["three_ds_authenticated"] is True
    assert flags["is_trusted_device"] is True
    assert flags["avs_match"] is True
    assert flags["cvv_match"] is True
    assert flags["is_tokenized"] is True
    assert flags["is_recurring_customer"] is True
    assert flags["cardholder_present"] is True
    assert flags["is_known_merchant"] is True


def test_counter_evidence_flags_response_codes():
    """Test AVS and CVV response codes."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "avs_response": "Y",
            "cvv_response": "Y",
        }
    )
    assert flags["avs_match"] is True
    assert flags["cvv_match"] is True


def test_counter_evidence_flags_payment_token():
    """Test payment token indicator."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "payment_token_present": True,
        }
    )
    assert flags["is_tokenized"] is True


def test_counter_evidence_flags_recurring_alternate():
    """Test recurring payment alternate key."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "recurring_payment": True,
        }
    )
    assert flags["is_recurring_customer"] is True


def test_counter_evidence_flags_none_values():
    """Test None values are treated as False."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(
        {
            "three_ds_authenticated": None,
            "is_trusted_device": None,
        }
    )
    assert flags["three_ds_authenticated"] is False
    assert flags["is_trusted_device"] is False


def test_counter_evidence_flags_non_dict():
    """Test non-dict input returns empty dict."""
    engine = SimilarityEngine.__new__(SimilarityEngine)
    flags = engine._counter_evidence_flags(None)
    assert flags == {}
    flags = engine._counter_evidence_flags("not a dict")
    assert flags == {}
