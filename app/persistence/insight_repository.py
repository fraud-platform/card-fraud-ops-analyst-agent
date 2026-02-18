"""Insight repository - CRUD for insights and evidence."""

import json
import uuid
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.persistence.base import row_to_dict
from app.utils.clock import utc_now


class InsightRepository:
    """CRUD operations for ops_agent_insights and ops_agent_evidence."""

    def __init__(self, session: AsyncSession):
        self.session = session

    async def upsert_insight(
        self,
        transaction_id: str,
        severity: str,
        summary: str,
        insight_type: str,
        model_mode: str,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """Insert or update insight (idempotent)."""
        insight_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_insights
                (insight_id, transaction_id, severity, insight_summary, insight_type,
                 generated_at, model_mode, idempotency_key)
            VALUES
                (:insight_id, :transaction_id, :severity, :summary, :insight_type,
                 :generated_at, :model_mode, :idempotency_key)
            ON CONFLICT (idempotency_key) DO UPDATE
            SET severity = EXCLUDED.severity,
                insight_summary = EXCLUDED.insight_summary,
                insight_type = EXCLUDED.insight_type,
                generated_at = EXCLUDED.generated_at,
                model_mode = EXCLUDED.model_mode
            RETURNING insight_id, transaction_id, severity, insight_summary AS summary, insight_type,
                      generated_at, model_mode
        """)
        result = await self.session.execute(
            query,
            {
                "insight_id": insight_id,
                "transaction_id": transaction_id,
                "severity": severity,
                "summary": summary,
                "insight_type": insight_type,
                "generated_at": now,
                "model_mode": model_mode,
                "idempotency_key": idempotency_key,
            },
        )
        row = result.fetchone()
        if row is None:
            select_query = text("""
                SELECT insight_id, transaction_id, severity, insight_summary AS summary, insight_type,
                       generated_at, model_mode
                FROM fraud_gov.ops_agent_insights
                WHERE idempotency_key = :idempotency_key
            """)
            result = await self.session.execute(select_query, {"idempotency_key": idempotency_key})
            row = result.fetchone()

        return row_to_dict(row)

    async def add_evidence(
        self,
        insight_id: str,
        evidence_kind: str,
        evidence_payload: dict[str, Any],
    ) -> dict[str, Any]:
        """Add evidence to an insight."""
        evidence_id = str(uuid.uuid7())
        now = utc_now()

        query = text("""
            INSERT INTO fraud_gov.ops_agent_evidence
                (evidence_id, insight_id, evidence_kind, evidence_payload, created_at)
            VALUES
                (:evidence_id, :insight_id, :evidence_kind, :evidence_payload, :created_at)
            RETURNING evidence_id, insight_id, evidence_kind, evidence_payload, created_at
        """)
        result = await self.session.execute(
            query,
            {
                "evidence_id": evidence_id,
                "insight_id": insight_id,
                "evidence_kind": evidence_kind,
                "evidence_payload": json.dumps(evidence_payload),
                "created_at": now,
            },
        )
        return row_to_dict(result.fetchone())

    async def get_insights_for_transaction(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get all insights for a transaction."""
        query = text("""
            SELECT insight_id, transaction_id, severity,
                   insight_summary AS summary,  -- Alias for schema compatibility
                   insight_type, generated_at, model_mode
            FROM fraud_gov.ops_agent_insights
            WHERE transaction_id = :transaction_id
            ORDER BY generated_at DESC
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get_insights_with_evidence(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get all insights for a transaction with evidence (single query - no N+1)."""
        query = text("""
            SELECT
                i.insight_id, i.transaction_id, i.severity,
                i.insight_summary AS summary,  -- Alias for schema compatibility
                i.insight_type, i.generated_at, i.model_mode,
                COALESCE(
                    jsonb_agg(
                        jsonb_build_object(
                            'evidence_id', e.evidence_id,
                            'evidence_kind', e.evidence_kind,
                            'evidence_payload', e.evidence_payload,
                            'created_at', e.created_at
                        ) ORDER BY e.created_at ASC
                    ) FILTER (WHERE e.evidence_id IS NOT NULL),
                    '[]'::jsonb
                ) AS evidence
            FROM fraud_gov.ops_agent_insights i
            LEFT JOIN fraud_gov.ops_agent_evidence e ON e.insight_id = i.insight_id
            WHERE i.transaction_id = :transaction_id
            GROUP BY i.insight_id, i.transaction_id, i.severity, i.insight_summary,
                     i.insight_type, i.generated_at, i.model_mode
            ORDER BY i.generated_at DESC
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})

        insights = []
        for row in result.fetchall():
            insight_dict = row_to_dict(row)
            # Convert JSONB evidence list to Python list
            insight_dict["evidence"] = list(insight_dict.get("evidence", []))
            insights.append(insight_dict)

        return insights

    async def get_evidence(self, insight_id: str) -> list[dict[str, Any]]:
        """Get all evidence for an insight."""
        query = text("""
            SELECT evidence_id, insight_id, evidence_kind, evidence_payload, created_at
            FROM fraud_gov.ops_agent_evidence
            WHERE insight_id = :insight_id
            ORDER BY created_at ASC
        """)
        result = await self.session.execute(query, {"insight_id": insight_id})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get(self, insight_id: str) -> dict[str, Any] | None:
        """Get insight by ID."""
        query = text("""
            SELECT insight_id, transaction_id, severity,
                   insight_summary AS summary,  -- Alias for schema compatibility
                   insight_type, generated_at, model_mode
            FROM fraud_gov.ops_agent_insights
            WHERE insight_id = :insight_id
        """)
        result = await self.session.execute(query, {"insight_id": insight_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)
