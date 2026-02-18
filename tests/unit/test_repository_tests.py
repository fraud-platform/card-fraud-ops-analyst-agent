"""Unit tests for repositories (simplified version)."""

from unittest.mock import AsyncMock, MagicMock

import pytest


def create_mock_row(**kwargs):
    """Create a mock row that behaves like a SQLAlchemy row."""
    mock_row = MagicMock()
    mock_row._mapping = kwargs
    # Also set attributes for direct access
    for key, value in kwargs.items():
        setattr(mock_row, key, value)
    return mock_row


# =============================================================================
# Recommendation Repository Tests
# =============================================================================


@pytest.mark.asyncio
async def test_upsert_recommendation_insert():
    """Test inserting a new recommendation."""
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        recommendation_id="rec-1",
        insight_id="insight-1",
        type="rule_candidate",
        payload='{"title": "Test"}',
        status="OPEN",
        acknowledged_by=None,
        acknowledged_at=None,
        created_at="2026-02-15T10:00:00Z",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = RecommendationRepository(mock_session)
    result = await repo.upsert_recommendation(
        insight_id="insight-1",
        recommendation_type="rule_candidate",
        payload={"title": "Test"},
        idempotency_key="key-1",
    )

    print("\n[RECOMMENDATION_REPO] Upsert (insert):")
    print(f"  recommendation_id: {result['recommendation_id']}")
    print(f"  status: {result['status']}")

    assert result["recommendation_id"] == "rec-1"
    assert result["status"] == "OPEN"


@pytest.mark.asyncio
async def test_update_status():
    """Test updating recommendation status."""
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        recommendation_id="rec-1",
        insight_id="insight-1",
        type="rule_candidate",
        payload='{"title": "Test"}',
        status="ACKNOWLEDGED",
        acknowledged_by="user-123",
        acknowledged_at="2026-02-15T11:00:00Z",
        created_at="2026-02-15T10:00:00Z",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = RecommendationRepository(mock_session)
    result = await repo.update_status(
        recommendation_id="rec-1",
        status="ACKNOWLEDGED",
        acknowledged_by="user-123",
    )

    print("\n[RECOMMENDATION_REPO] Update status:")
    print(f"  status: {result['status']}")
    print(f"  acknowledged_by: {result['acknowledged_by']}")

    assert result["status"] == "ACKNOWLEDGED"
    assert result["acknowledged_by"] == "user-123"


@pytest.mark.asyncio
async def test_get_recommendation():
    """Test getting recommendation by ID."""
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        recommendation_id="rec-1",
        insight_id="insight-1",
        type="rule_candidate",
        payload='{"title": "Test"}',
        status="OPEN",
        acknowledged_by=None,
        acknowledged_at=None,
        created_at="2026-02-15T10:00:00Z",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = RecommendationRepository(mock_session)
    result = await repo.get("rec-1")

    print("\n[RECOMMENDATION_REPO] Get by ID:")
    print(f"  recommendation_id: {result['recommendation_id']}")

    assert result["recommendation_id"] == "rec-1"


@pytest.mark.asyncio
async def test_get_recommendation_not_found():
    """Test getting non-existent recommendation returns None."""
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    repo = RecommendationRepository(mock_session)
    result = await repo.get("nonexistent")

    print("\n[RECOMMENDATION_REPO] Get nonexistent:")
    print(f"  result: {result}")

    assert result is None


@pytest.mark.asyncio
async def test_list_by_insight_id():
    """Test listing recommendations by insight ID."""
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            recommendation_id="rec-1",
            insight_id="insight-1",
            type="rule_candidate",
            payload='{"title": "Test 1"}',
            status="OPEN",
            acknowledged_by=None,
            acknowledged_at=None,
            created_at="2026-02-15T10:00:00Z",
        ),
        create_mock_row(
            recommendation_id="rec-2",
            insight_id="insight-1",
            type="investigate",
            payload='{"title": "Test 2"}',
            status="OPEN",
            acknowledged_by=None,
            acknowledged_at=None,
            created_at="2026-02-15T09:00:00Z",
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    repo = RecommendationRepository(mock_session)
    results = await repo.list_by_insight_id("insight-1")

    print("\n[RECOMMENDATION_REPO] List by insight_id:")
    print(f"  Count: {len(results)}")
    print(f"  Types: {[r['type'] for r in results]}")

    assert len(results) == 2
    assert all(r["insight_id"] == "insight-1" for r in results)


@pytest.mark.asyncio
async def test_list_open_rejects_invalid_severity_filter():
    """Test worklist filter validation rejects unsupported severity values."""
    from app.core.errors import ValidationError
    from app.persistence.recommendation_repository import RecommendationRepository

    mock_session = AsyncMock()
    repo = RecommendationRepository(mock_session)

    with pytest.raises(ValidationError, match="Invalid severity filter"):
        await repo.list_open(severity="invalid")

    mock_session.execute.assert_not_called()


# =============================================================================
# Insight Repository Tests
# =============================================================================


@pytest.mark.asyncio
async def test_upsert_insight_insert():
    """Test inserting a new insight."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        insight_id="insight-1",
        transaction_id="txn-1",
        severity="HIGH",
        summary="High fraud risk detected",
        insight_type="fraud_analysis",
        generated_at="2026-02-15T10:00:00Z",
        model_mode="deterministic",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    result = await repo.upsert_insight(
        transaction_id="txn-1",
        severity="HIGH",
        summary="High fraud risk detected",
        insight_type="fraud_analysis",
        model_mode="deterministic",
        idempotency_key="key-1",
    )

    print("\n[INSIGHT_REPO] Upsert insight (insert):")
    print(f"  insight_id: {result['insight_id']}")
    print(f"  summary: {result['summary']}")

    assert result["insight_id"] == "insight-1"
    assert result["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_add_evidence():
    """Test adding evidence to an insight."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        evidence_id="ev-1",
        insight_id="insight-1",
        evidence_kind="pattern_velocity",
        evidence_payload='{"pattern_name": "velocity", "score": 0.8}',
        created_at="2026-02-15T10:00:00Z",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    result = await repo.add_evidence(
        insight_id="insight-1",
        evidence_kind="pattern_velocity",
        evidence_payload={"pattern_name": "velocity", "score": 0.8},
    )

    print("\n[INSIGHT_REPO] Add evidence:")
    print(f"  evidence_id: {result['evidence_id']}")
    print(f"  evidence_kind: {result['evidence_kind']}")

    assert result["evidence_id"] == "ev-1"
    assert result["evidence_kind"] == "pattern_velocity"


@pytest.mark.asyncio
async def test_get_insights_for_transaction():
    """Test getting all insights for a transaction."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            insight_id="insight-1",
            transaction_id="txn-1",
            severity="HIGH",
            summary="High risk",
            insight_type="fraud_analysis",
            generated_at="2026-02-15T10:00:00Z",
            model_mode="deterministic",
        ),
        create_mock_row(
            insight_id="insight-2",
            transaction_id="txn-1",
            severity="MEDIUM",
            summary="Medium risk",
            insight_type="fraud_analysis",
            generated_at="2026-02-15T09:00:00Z",
            model_mode="deterministic",
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    results = await repo.get_insights_for_transaction("txn-1")

    print("\n[INSIGHT_REPO] Get insights for transaction:")
    print(f"  Count: {len(results)}")
    print(f"  Severities: {[r['severity'] for r in results]}")

    assert len(results) == 2
    assert all(r["transaction_id"] == "txn-1" for r in results)


@pytest.mark.asyncio
async def test_get_evidence():
    """Test getting evidence for an insight."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            evidence_id="ev-1",
            insight_id="insight-1",
            evidence_kind="pattern_velocity",
            evidence_payload='{"score": 0.8}',
            created_at="2026-02-15T10:00:00Z",
        ),
        create_mock_row(
            evidence_id="ev-2",
            insight_id="insight-1",
            evidence_kind="similarity",
            evidence_payload='{"score": 0.9}',
            created_at="2026-02-15T10:01:00Z",
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    results = await repo.get_evidence("insight-1")

    print("\n[INSIGHT_REPO] Get evidence:")
    print(f"  Count: {len(results)}")
    print(f"  Kinds: {[e['evidence_kind'] for e in results]}")

    assert len(results) == 2
    assert all(e["insight_id"] == "insight-1" for e in results)


@pytest.mark.asyncio
async def test_get_insight():
    """Test getting insight by ID."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        insight_id="insight-1",
        transaction_id="txn-1",
        severity="HIGH",
        summary="High risk",
        insight_type="fraud_analysis",
        generated_at="2026-02-15T10:00:00Z",
        model_mode="deterministic",
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    result = await repo.get("insight-1")

    print("\n[INSIGHT_REPO] Get by ID:")
    print(f"  insight_id: {result['insight_id']}")
    print(f"  severity: {result['severity']}")

    assert result["insight_id"] == "insight-1"
    assert result["severity"] == "HIGH"


@pytest.mark.asyncio
async def test_get_insight_not_found():
    """Test getting non-existent insight returns None."""
    from app.persistence.insight_repository import InsightRepository

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    repo = InsightRepository(mock_session)
    result = await repo.get("nonexistent")

    print("\n[INSIGHT_REPO] Get nonexistent:")
    print(f"  result: {result}")

    assert result is None


# =============================================================================
# Context Reader Tests
# =============================================================================


@pytest.mark.asyncio
async def test_get_transaction():
    """Test getting a transaction by business key."""
    from app.persistence.context_reader import ContextReader

    mock_session = AsyncMock()
    mock_row = create_mock_row(
        id="pk-1",
        transaction_id="txn-1",
        amount=100.50,
        currency="USD",
        merchant_id="merch-1",
        merchant_category="5411",
        card_id="card-1",
        card_last_four="1234",
        transaction_timestamp="2026-02-15T10:00:00Z",
        status="DECLINE",
        decline_reason="fraud suspicion",
        fraud_score=0.92,
        risk_level="HIGH",
        velocity_snapshot={},
        velocity_results={},
        transaction_context={},
    )

    mock_result = MagicMock()
    mock_result.fetchone.return_value = mock_row
    mock_session.execute.return_value = mock_result

    reader = ContextReader(mock_session)
    result = await reader.get_transaction("txn-1")

    print("\n[CONTEXT_READER] Get transaction:")
    print(f"  transaction_id: {result['transaction_id']}")
    print(f"  amount: {result['amount']}")
    print(f"  status: {result['status']}")

    assert result["transaction_id"] == "txn-1"
    assert result["amount"] == 100.50
    assert result["status"] == "DECLINE"


@pytest.mark.asyncio
async def test_get_transaction_not_found():
    """Test getting non-existent transaction returns None."""
    from app.persistence.context_reader import ContextReader

    mock_session = AsyncMock()
    mock_result = MagicMock()
    mock_result.fetchone.return_value = None
    mock_session.execute.return_value = mock_result

    reader = ContextReader(mock_session)
    result = await reader.get_transaction("nonexistent")

    print("\n[CONTEXT_READER] Get nonexistent:")
    print(f"  result: {result}")

    assert result is None


@pytest.mark.asyncio
async def test_get_transaction_rule_matches():
    """Test getting rule matches for a transaction."""
    from app.persistence.context_reader import ContextReader

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            id="match-1",
            rule_id="rule-1",
            rule_name="high_velocity_rule",
            triggered_at="2026-02-15T10:00:00Z",
            action="DECLINE",
            score=0.85,
            metadata='{"matched": true}',
            matched=True,
            contributing=True,
            match_reason="Velocity exceeded threshold",
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    reader = ContextReader(mock_session)
    results = await reader.get_transaction_rule_matches("txn-1")

    print("\n[CONTEXT_READER] Get rule matches:")
    print(f"  Count: {len(results)}")
    print(f"  Rule names: {[m['rule_name'] for m in results]}")

    assert len(results) == 1
    assert results[0]["rule_name"] == "high_velocity_rule"


@pytest.mark.asyncio
async def test_get_card_history():
    """Test getting card history."""
    from app.persistence.context_reader import ContextReader

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            transaction_id="txn-1",
            amount=100.0,
            merchant_id="merch-1",
            merchant_category="5411",
            transaction_timestamp="2026-02-15T10:00:00Z",
            status="APPROVE",
            decline_reason=None,
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    reader = ContextReader(mock_session)
    results = await reader.get_card_history("card-1", hours_back=24)

    print("\n[CONTEXT_READER] Get card history:")
    print(f"  Count: {len(results)}")
    print(f"  Amounts: {[t['amount'] for t in results]}")

    assert len(results) == 1
    assert results[0]["amount"] == 100.0


@pytest.mark.asyncio
async def test_get_merchant_history():
    """Test getting merchant history."""
    from app.persistence.context_reader import ContextReader

    mock_session = AsyncMock()
    mock_rows = [
        create_mock_row(
            transaction_id="txn-1",
            amount=100.0,
            card_id="card-1",
            card_last_four="1234",
            transaction_timestamp="2026-02-15T10:00:00Z",
            status="APPROVE",
            decline_reason=None,
        ),
    ]

    mock_result = MagicMock()
    mock_result.fetchall.return_value = mock_rows
    mock_session.execute.return_value = mock_result

    reader = ContextReader(mock_session)
    results = await reader.get_merchant_history("merch-1", hours_back=24)

    print("\n[CONTEXT_READER] Get merchant history:")
    print(f"  Count: {len(results)}")
    print(f"  Card last fours: {[t['card_last_four'] for t in results]}")

    assert len(results) == 1
    assert results[0]["card_last_four"] == "1234"
