"""Integration tests for repository operations with real database."""

from __future__ import annotations

import os
import uuid

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine
from sqlalchemy.orm import sessionmaker

from app.core.config import to_asyncpg_url
from app.persistence.insight_repository import InsightRepository
from app.persistence.recommendation_repository import RecommendationRepository
from app.persistence.rule_draft_repository import RuleDraftRepository
from app.persistence.tool_log_repository import ToolLogRepository


def _require_database_url() -> str:
    database_url = os.environ.get("DATABASE_URL_APP", "").strip()
    if not database_url:
        pytest.skip("DATABASE_URL_APP is not configured for integration tests")
    return to_asyncpg_url(database_url)


@pytest.fixture
async def session():
    """Create async session for integration tests."""
    database_url = _require_database_url()
    engine = create_async_engine(database_url)
    async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)
    async with async_session() as s:
        yield s
        await s.commit()
    await engine.dispose()


async def _create_investigation(session: AsyncSession) -> str:
    """Helper to create an investigation and return its ID."""
    investigation_id = str(uuid.uuid7())
    await session.execute(
        text(
            f"INSERT INTO fraud_gov.ops_agent_investigations "
            f"(id, transaction_id, mode, status, priority, started_at, created_at, updated_at) "
            f"VALUES ('{investigation_id}', '{uuid.uuid7()}', 'FULL', 'COMPLETED', 'MEDIUM', NOW(), NOW(), NOW())"
        )
    )
    return investigation_id


@pytest.mark.integration
@pytest.mark.asyncio
class TestToolLogRepository:
    """Integration tests for tool_log_repository."""

    async def test_log_execution_inserts_record(self, session):
        """Tool log insert uses correct column names."""
        investigation_id = await _create_investigation(session)
        repo = ToolLogRepository(session)

        result = await repo.log_execution(
            investigation_id=investigation_id,
            tool_name="context_tool",
            step_number=1,
            input_summary={"test": "input"},
            output_summary={"test": "output"},
            execution_time_ms=100,
            status="SUCCESS",
        )

        assert result["tool_name"] == "context_tool"
        assert result["status"] == "SUCCESS"
        assert result["step_number"] == 1


@pytest.mark.integration
@pytest.mark.asyncio
class TestInsightRepository:
    """Integration tests for insight_repository."""

    async def test_upsert_insight_uses_correct_columns(self, session):
        """Insight insert uses 'summary' not 'insight_summary'."""
        repo = InsightRepository(session)
        transaction_id = str(uuid.uuid7())
        idempotency_key = f"test-{uuid.uuid4()}"

        result = await repo.upsert_insight(
            transaction_id=transaction_id,
            severity="HIGH",
            summary="Test insight summary",
            insight_type="test",
            model_mode="agentic",
            idempotency_key=idempotency_key,
        )

        assert result["severity"] == "HIGH"

    async def test_add_evidence(self, session):
        """Evidence insert works correctly."""
        repo = InsightRepository(session)

        insight_id = str(uuid.uuid7())
        transaction_id = str(uuid.uuid7())

        await session.execute(
            text(
                f"INSERT INTO fraud_gov.ops_agent_insights "
                f"(insight_id, transaction_id, severity, summary, insight_type, model_mode, generated_at) "
                f"VALUES ('{insight_id}', '{transaction_id}', 'LOW', 'Test', 'test', 'agentic', NOW())"
            )
        )

        result = await repo.add_evidence(
            insight_id=insight_id,
            evidence_kind="pattern",
            evidence_payload={"score": 0.8},
        )

        assert result["evidence_kind"] == "pattern"


@pytest.mark.integration
@pytest.mark.asyncio
class TestRecommendationRepository:
    """Integration tests for recommendation_repository."""

    async def test_upsert_recommendation_uses_correct_columns(self, session):
        """Recommendation insert uses 'type' and 'payload' columns."""
        repo = RecommendationRepository(session)

        insight_id = str(uuid.uuid7())
        transaction_id = str(uuid.uuid7())
        idempotency_key = f"test-{uuid.uuid4()}"

        await session.execute(
            text(
                f"INSERT INTO fraud_gov.ops_agent_insights "
                f"(insight_id, transaction_id, severity, summary, insight_type, model_mode, generated_at) "
                f"VALUES ('{insight_id}', '{transaction_id}', 'LOW', 'Test', 'test', 'agentic', NOW())"
            )
        )

        result = await repo.upsert_recommendation(
            insight_id=insight_id,
            recommendation_type="REVIEW",
            payload={"action": "block"},
            idempotency_key=idempotency_key,
            title="Test recommendation",
            impact="High impact",
        )

        assert result["type"] == "REVIEW"

    async def test_list_open_joins_insight_correctly(self, session):
        """list_open uses correct column aliases."""
        repo = RecommendationRepository(session)

        recommendations, cursor = await repo.list_open(limit=10)

        assert isinstance(recommendations, list)
        for rec in recommendations:
            assert "type" in rec
            assert "payload" in rec


@pytest.mark.integration
@pytest.mark.asyncio
class TestRuleDraftRepository:
    """Integration tests for rule_draft_repository."""

    async def test_create_uses_correct_columns(self, session):
        """Rule draft insert uses new DDL columns."""
        investigation_id = await _create_investigation(session)
        repo = RuleDraftRepository(session)

        result = await repo.create(
            investigation_id=investigation_id,
            rule_name="Test Rule",
            rule_description="Test description",
            conditions=[{"field": "amount", "operator": ">", "value": 1000}],
            thresholds={"confidence": 0.8},
            metadata={"source": "test"},
        )

        assert result["rule_name"] == "Test Rule"
        assert result["rule_description"] == "Test description"
        assert "conditions" in result
        assert "thresholds" in result

    async def test_get_by_investigation(self, session):
        """Get rule draft by investigation ID."""
        investigation_id = await _create_investigation(session)
        repo = RuleDraftRepository(session)

        await repo.create(
            investigation_id=investigation_id,
            rule_name="Test Rule 2",
            rule_description="Test",
            conditions=[],
            thresholds={},
        )

        result = await repo.get_by_investigation(investigation_id)
        assert result is not None
        assert result["rule_name"] == "Test Rule 2"
