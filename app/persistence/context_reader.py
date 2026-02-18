"""Context reader - READ-ONLY queries on TM tables."""

from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import ValidationError
from app.persistence.base import row_to_dict

MIN_HISTORY_HOURS = 1
MAX_HISTORY_HOURS = 24 * 365  # 1 year


class ContextReader:
    """Read-only queries on TM tables for context building."""

    def __init__(self, session: AsyncSession):
        self.session = session

    @staticmethod
    def _validate_hours_back(hours_back: int) -> None:
        """Validate history windows to prevent invalid/fat queries."""
        if hours_back < MIN_HISTORY_HOURS or hours_back > MAX_HISTORY_HOURS:
            raise ValidationError(
                "hours_back must be between 1 and 8760",
                details={
                    "min": MIN_HISTORY_HOURS,
                    "max": MAX_HISTORY_HOURS,
                    "received": hours_back,
                },
            )

    async def get_transaction(self, transaction_id: str) -> dict[str, Any] | None:
        """Get transaction by business key."""
        query = text("""
            SELECT id, transaction_id,
                   transaction_amount AS amount,
                   transaction_currency AS currency,
                   merchant_id,
                   merchant_category_code AS merchant_category,
                   card_id,
                   card_last4 AS card_last_four,
                   transaction_timestamp,
                   decision AS status,
                   decision_reason AS decline_reason,
                   decision_score AS fraud_score,
                   risk_level,
                   velocity_snapshot,
                   velocity_results,
                   transaction_context
            FROM fraud_gov.transactions
            WHERE transaction_id = :transaction_id
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def get_transaction_rule_matches(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get rule matches for a transaction."""
        query = text("""
            SELECT trm.id, trm.rule_id, trm.rule_name, trm.evaluated_at AS triggered_at,
                   trm.rule_action AS action, trm.match_score AS score, trm.rule_output AS metadata,
                   trm.matched, trm.contributing, trm.match_reason
            FROM fraud_gov.transaction_rule_matches trm
            JOIN fraud_gov.transactions t ON t.id = trm.transaction_id
            WHERE t.transaction_id = :transaction_id
            ORDER BY trm.evaluated_at DESC
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get_transaction_reviews(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get reviews for a transaction."""
        query = text("""
            SELECT tr.id, tr.assigned_analyst_id AS reviewed_by,
                   tr.first_reviewed_at AS reviewed_at,
                   tr.resolution_code AS decision,
                   tr.resolution_notes AS notes,
                   tr.case_id, tr.status, tr.priority
            FROM fraud_gov.transaction_reviews tr
            JOIN fraud_gov.transactions t ON t.id = tr.transaction_id
            WHERE t.transaction_id = :transaction_id
            ORDER BY tr.created_at DESC
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get_analyst_notes(self, transaction_id: str) -> list[dict[str, Any]]:
        """Get analyst notes for a transaction."""
        query = text("""
            SELECT an.id, an.note_content AS note_text, an.analyst_id AS created_by,
                   an.analyst_name, an.note_type, an.created_at
            FROM fraud_gov.analyst_notes an
            JOIN fraud_gov.transactions t ON t.id = an.transaction_id
            WHERE t.transaction_id = :transaction_id
              AND an.is_private = FALSE
            ORDER BY an.created_at DESC
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get_transaction_case(self, transaction_id: str) -> dict[str, Any] | None:
        """Get case for a transaction (via transaction_reviews.case_id)."""
        query = text("""
            SELECT tc.id, tc.case_number AS case_id, tc.case_type, tc.case_status AS status,
                   tc.assigned_analyst_id AS assigned_to, tc.risk_level AS priority,
                   tc.title, tc.created_at
            FROM fraud_gov.transaction_cases tc
            JOIN fraud_gov.transaction_reviews tr ON tr.case_id = tc.id
            JOIN fraud_gov.transactions t ON t.id = tr.transaction_id
            WHERE t.transaction_id = :transaction_id
            ORDER BY tc.created_at DESC
            LIMIT 1
        """)
        result = await self.session.execute(query, {"transaction_id": transaction_id})
        row = result.fetchone()
        if row is None:
            return None
        return row_to_dict(row)

    async def get_card_history(self, card_id: str, hours_back: int = 24) -> list[dict[str, Any]]:
        """Get transaction history for a card within time window."""
        self._validate_hours_back(hours_back)
        query = text("""
            SELECT t.transaction_id, t.transaction_amount AS amount, t.merchant_id,
                   t.merchant_category_code AS merchant_category,
                   t.transaction_timestamp, t.decision AS status, t.decision_reason AS decline_reason
            FROM fraud_gov.transactions t
            WHERE t.card_id = :card_id
              AND t.transaction_timestamp >= NOW() - MAKE_INTERVAL(hours => :hours_back)
            ORDER BY t.transaction_timestamp DESC
        """)
        result = await self.session.execute(query, {"card_id": card_id, "hours_back": hours_back})
        return [row_to_dict(row) for row in result.fetchall()]

    async def get_merchant_history(
        self, merchant_id: str, hours_back: int = 24
    ) -> list[dict[str, Any]]:
        """Get transaction history for a merchant within time window."""
        self._validate_hours_back(hours_back)
        query = text("""
            SELECT t.transaction_id, t.transaction_amount AS amount, t.card_id,
                   t.card_last4 AS card_last_four,
                   t.transaction_timestamp, t.decision AS status, t.decision_reason AS decline_reason
            FROM fraud_gov.transactions t
            WHERE t.merchant_id = :merchant_id
              AND t.transaction_timestamp >= NOW() - MAKE_INTERVAL(hours => :hours_back)
            ORDER BY t.transaction_timestamp DESC
        """)
        result = await self.session.execute(
            query, {"merchant_id": merchant_id, "hours_back": hours_back}
        )
        return [row_to_dict(row) for row in result.fetchall()]
