"""Similarity engine - DB-bound module.

When `VECTOR_ENABLED` is false, this module behaves as a stub and returns a
zero-score SimilarityResult (to preserve Phase 1 behavior).
"""

import asyncio
import logging
import time
from typing import Any

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.similarity_engine_core import evaluate_similarity
from app.clients.embedding_client import EmbeddingClient
from app.core.config import get_settings
from app.core.errors import DependencyError
from app.core.metrics import (
    ops_agent_db_query_failures_total,
    ops_agent_db_query_latency_seconds,
    ops_agent_dependency_failures_total,
)
from app.utils.clock import utc_now

log = logging.getLogger(__name__)


class SimilarityEngine:
    """DB-bound similarity engine.

    Vector search is guarded behind `VECTOR_ENABLED`.
    """

    def __init__(self, session: AsyncSession):
        self.session = session
        self._settings = get_settings()
        self._embedding_client = EmbeddingClient(self._settings)

    async def analyze(self, context: dict[str, Any]) -> dict[str, Any]:
        """Run similarity analysis.

        When VECTOR_ENABLED is false, returns a zero-score stub result.
        When enabled, generates an embedding for the transaction, upserts it
        into the embeddings table, and searches for similar past transactions.
        """
        transaction = context.get("transaction")
        txn_pk_id = context.get("transaction_pk_id", "")

        if not self._settings.vector_search.enabled:
            result = evaluate_similarity(transaction, [])
            return self._as_payload(
                result,
                vector_feature_enabled=False,
                vector_stage_executed=False,
                vector_status="disabled",
                vector_error=None,
            )

        vector_matches: list[dict[str, Any]] = []
        try:
            query_embedding = await self._generate_embedding(transaction)
            # Best-effort: upsert so similarity coverage improves over time.
            await self._upsert_embedding(txn_pk_id, query_embedding)
            vector_matches = await self._vector_search(query_embedding, txn_pk_id, transaction)
        except Exception as exc:
            # Fail closed when VECTOR_ENABLED=true so test/prod environments
            # never silently run without vector evidence.
            ops_agent_dependency_failures_total.labels(dependency="vector_search").inc()
            log.error(
                "Vector embedding unavailable while VECTOR_ENABLED=true",
                extra={
                    "error": str(exc),
                    "transaction_pk_id": str(txn_pk_id),
                    "vector_api_base": self._settings.vector_search.api_base,
                    "vector_model_name": self._settings.vector_search.model_name,
                },
            )
            raise DependencyError(
                "Vector similarity unavailable while VECTOR_ENABLED=true. "
                "Fix vector provider configuration (VECTOR_API_BASE / VECTOR_MODEL_NAME / VECTOR_API_KEY)."
            ) from exc

        attribute_matches = await self._attribute_search(txn_pk_id, transaction)
        similar_transactions = self._merge_matches(vector_matches, attribute_matches)

        result = evaluate_similarity(transaction, similar_transactions)

        return self._as_payload(
            result,
            vector_feature_enabled=True,
            vector_stage_executed=True,
            vector_status="ok",
            vector_error=None,
        )

    @staticmethod
    def _as_payload(
        result: Any,
        *,
        vector_feature_enabled: bool,
        vector_stage_executed: bool,
        vector_status: str,
        vector_error: str | None,
    ) -> dict[str, Any]:
        """Return canonical similarity output."""
        matches = [
            {
                "match_id": m.match_id,
                "match_type": m.match_type,
                "similarity_score": m.similarity_score,
                "details": m.details,
                "counter_evidence": m.counter_evidence,
            }
            for m in getattr(result, "matches", [])
        ]
        overall_score = float(getattr(result, "overall_score", 0.0))
        counter_evidence = getattr(result, "counter_evidence", None)
        vector_match_count = sum(1 for match in matches if match.get("match_type") == "vector")
        attribute_match_count = sum(
            1 for match in matches if match.get("match_type") == "attribute"
        )

        return {
            "similarity_result": result,
            "matches": matches,
            "overall_score": overall_score,
            "counter_evidence": counter_evidence,
            "similar_transactions": matches,
            "vector_feature_enabled": vector_feature_enabled,
            "vector_stage_executed": vector_stage_executed,
            "vector_status": vector_status,
            "vector_error": vector_error,
            "vector_match_count": vector_match_count,
            "attribute_match_count": attribute_match_count,
        }

    @staticmethod
    def _counter_evidence_flags(transaction_context: Any) -> dict[str, bool]:
        """Extract normalized counter-evidence booleans from TM context JSON."""
        if not isinstance(transaction_context, dict):
            return {}

        three_ds = transaction_context.get("three_ds_authenticated")
        if three_ds is None:
            three_ds = transaction_context.get("3ds_verified")

        trusted_device = transaction_context.get("is_trusted_device")
        if trusted_device is None:
            trusted_device = transaction_context.get("device_trusted")

        avs_match = transaction_context.get("avs_match")
        if avs_match is None:
            avs_match = transaction_context.get("avs_response")

        cvv_match = transaction_context.get("cvv_match")
        if cvv_match is None:
            cvv_match = transaction_context.get("cvv_response")

        is_tokenized = transaction_context.get("is_tokenized")
        if is_tokenized is None:
            is_tokenized = transaction_context.get("payment_token_present")

        is_recurring = transaction_context.get("is_recurring_customer")
        if is_recurring is None:
            is_recurring = transaction_context.get("recurring_payment")

        cardholder_present = transaction_context.get("cardholder_present")

        is_known_merchant = transaction_context.get("is_known_merchant")

        return {
            "three_ds_authenticated": bool(three_ds) if three_ds is not None else False,
            "is_trusted_device": bool(trusted_device) if trusted_device is not None else False,
            "avs_match": bool(avs_match) if avs_match is not None else False,
            "cvv_match": bool(cvv_match) if cvv_match is not None else False,
            "is_tokenized": bool(is_tokenized) if is_tokenized is not None else False,
            "is_recurring_customer": bool(is_recurring) if is_recurring is not None else False,
            "cardholder_present": bool(cardholder_present)
            if cardholder_present is not None
            else False,
            "is_known_merchant": bool(is_known_merchant)
            if is_known_merchant is not None
            else False,
        }

    def _embedding_text(self, transaction: Any) -> str:
        if isinstance(transaction, dict):
            amount = transaction.get("amount")
            currency = transaction.get("currency")
            merchant_id = transaction.get("merchant_id")
            merchant_category = transaction.get("merchant_category")
            status = transaction.get("status")
            decline_reason = transaction.get("decline_reason")
            risk_level = transaction.get("risk_level")
        else:
            amount = getattr(transaction, "amount", None)
            currency = getattr(transaction, "currency", None)
            merchant_id = getattr(transaction, "merchant_id", None)
            merchant_category = getattr(transaction, "merchant_category", None)
            status = getattr(transaction, "status", None)
            decline_reason = getattr(transaction, "decline_reason", None)
            risk_level = getattr(transaction, "risk_level", None)

        parts = [
            f"amount={amount}",
            f"currency={currency}",
            f"merchant_id={merchant_id}",
            f"merchant_category={merchant_category}",
            f"status={status}",
            f"decline_reason={decline_reason}",
            f"risk_level={risk_level}",
        ]
        return "\n".join(parts)

    async def _generate_embedding(self, transaction: Any) -> list[float]:
        text_to_embed = self._embedding_text(transaction)
        response = await self._embedding_client.embed(text_to_embed)
        if len(response.embedding) != self._settings.vector_search.dimension:
            raise ValueError(
                "Embedding dimension mismatch: "
                f"expected={self._settings.vector_search.dimension} got={len(response.embedding)}"
            )
        return response.embedding

    async def _upsert_embedding(self, txn_pk_id: str, embedding: list[float]) -> None:
        if not txn_pk_id:
            return

        query_vector = "[" + ",".join(str(float(v)) for v in embedding) + "]"
        query = text(
            """
            INSERT INTO fraud_gov.ops_agent_transaction_embeddings
                (transaction_id, embedding, model_name, created_at, updated_at)
            VALUES
                (CAST(:transaction_id AS uuid), CAST(:embedding AS vector), :model_name, NOW(), NOW())
            ON CONFLICT (transaction_id)
            DO UPDATE SET
                embedding = EXCLUDED.embedding,
                model_name = EXCLUDED.model_name,
                updated_at = NOW()
            """
        )

        await self.session.execute(
            query,
            {
                "transaction_id": str(txn_pk_id),
                "embedding": query_vector,
                "model_name": self._settings.vector_search.model_name,
            },
        )

    async def _vector_search(
        self, query_embedding: list[float], txn_pk_id: str, transaction: Any
    ) -> list[dict[str, Any]]:
        query_vector = "[" + ",".join(str(float(v)) for v in query_embedding) + "]"
        window_days = int(self._settings.vector_search.time_window_days)
        limit = int(self._settings.vector_search.search_limit)
        min_similarity = float(self._settings.vector_search.min_similarity)

        query = text(
            """
            SELECT
                t.transaction_id,
                t.transaction_amount AS amount,
                t.merchant_id,
                t.card_id,
                t.decision,
                t.transaction_timestamp,
                t.transaction_context,
                1 - (e.embedding <=> CAST(:query_vector AS vector)) AS similarity_score
            FROM fraud_gov.ops_agent_transaction_embeddings e
            JOIN fraud_gov.transactions t
              ON t.id = e.transaction_id
            WHERE
                (CAST(:exclude_id AS uuid) IS NULL OR t.id != CAST(:exclude_id AS uuid))
                AND t.transaction_timestamp >= NOW() - MAKE_INTERVAL(days => :window_days)
            ORDER BY e.embedding <=> CAST(:query_vector AS vector)
            LIMIT :limit
            """
        )

        attempts = max(1, int(self._settings.vector_search.retry_attempts))
        base_backoff_s = max(0.0, float(self._settings.vector_search.retry_backoff_seconds))
        started = utc_now()
        result = None
        for attempt in range(1, attempts + 1):
            try:
                query_start = time.perf_counter()
                result = await self.session.execute(
                    query,
                    {
                        "query_vector": query_vector,
                        "exclude_id": str(txn_pk_id) if txn_pk_id else None,
                        "window_days": window_days,
                        "limit": limit,
                    },
                )
                ops_agent_db_query_latency_seconds.labels(
                    query_name="similarity_vector_search"
                ).observe(time.perf_counter() - query_start)
                break
            except Exception as exc:
                ops_agent_db_query_failures_total.labels(
                    query_name="similarity_vector_search"
                ).inc()
                if attempt >= attempts:
                    raise
                backoff_s = base_backoff_s * (2 ** (attempt - 1))
                log.warning(
                    "Vector search query failed; retrying",
                    extra={
                        "attempt": attempt,
                        "max_attempts": attempts,
                        "backoff_s": backoff_s,
                        "error": str(exc),
                    },
                )
                await asyncio.sleep(backoff_s)
        assert result is not None

        if isinstance(transaction, dict):
            current_card_id = str(transaction.get("card_id") or "")
            current_merchant_id = str(transaction.get("merchant_id") or "")
        else:
            current_card_id = str(getattr(transaction, "card_id", "") or "")
            current_merchant_id = str(getattr(transaction, "merchant_id", "") or "")

        matches: list[dict[str, Any]] = []
        for row in result.fetchall():
            row_card_id = str(row.card_id) if row.card_id is not None else ""
            row_merchant_id = str(row.merchant_id) if row.merchant_id is not None else ""
            try:
                decision_value = row.decision
            except AttributeError:
                decision_value = None
            same_card = bool(current_card_id and row_card_id and row_card_id == current_card_id)
            same_merchant = bool(
                current_merchant_id and row_merchant_id and row_merchant_id == current_merchant_id
            )
            affinity_multiplier = 1.0 if same_card else (0.75 if same_merchant else 0.35)
            raw_score = float(row.similarity_score)
            adjusted_score = raw_score * affinity_multiplier

            if adjusted_score < min_similarity:
                continue
            counter_flags = self._counter_evidence_flags(getattr(row, "transaction_context", None))
            matches.append(
                {
                    "transaction_id": str(row.transaction_id),
                    "amount": float(row.amount) if row.amount is not None else 0.0,
                    "merchant_id": str(row.merchant_id) if row.merchant_id is not None else None,
                    "card_id": str(row.card_id) if row.card_id is not None else None,
                    "decision": str(decision_value) if decision_value is not None else None,
                    "transaction_timestamp": row.transaction_timestamp,
                    "match_type": "vector",
                    "similarity_score": adjusted_score,
                    **counter_flags,
                    "details": {
                        "raw_similarity_score": round(raw_score, 6),
                        "affinity_multiplier": affinity_multiplier,
                        "same_card": same_card,
                        "same_merchant": same_merchant,
                        "latency_ms": int((utc_now() - started).total_seconds() * 1000),
                    },
                }
            )
        return matches

    async def _attribute_search(self, txn_pk_id: str, transaction: Any) -> list[dict[str, Any]]:
        if isinstance(transaction, dict):
            card_id = transaction.get("card_id")
            merchant_id = transaction.get("merchant_id")
        else:
            card_id = getattr(transaction, "card_id", None)
            merchant_id = getattr(transaction, "merchant_id", None)

        if not card_id and not merchant_id:
            return []

        window_days = int(self._settings.vector_search.time_window_days)
        limit = int(min(self._settings.vector_search.search_limit, 20))

        query = text(
            """
            SELECT
                t.transaction_id,
                t.transaction_amount AS amount,
                t.merchant_id,
                t.card_id,
                t.decision,
                t.transaction_timestamp,
                t.transaction_context,
                CASE
                    WHEN t.card_id = :card_id AND t.merchant_id = :merchant_id THEN 0.8
                    WHEN t.card_id = :card_id THEN 0.6
                    WHEN t.merchant_id = :merchant_id THEN 0.4
                    ELSE 0.2
                END AS similarity_score
            FROM fraud_gov.transactions t
            WHERE
                (
                    (:card_id IS NOT NULL AND t.card_id = :card_id)
                    OR (:merchant_id IS NOT NULL AND t.merchant_id = :merchant_id)
                )
                AND (CAST(:exclude_id AS uuid) IS NULL OR t.id != CAST(:exclude_id AS uuid))
                AND t.transaction_timestamp >= NOW() - MAKE_INTERVAL(days => :window_days)
            ORDER BY similarity_score DESC, t.transaction_timestamp DESC
            LIMIT :limit
            """
        )

        try:
            query_start = time.perf_counter()
            result = await self.session.execute(
                query,
                {
                    "card_id": str(card_id) if card_id else None,
                    "merchant_id": str(merchant_id) if merchant_id else None,
                    "exclude_id": str(txn_pk_id) if txn_pk_id else None,
                    "window_days": window_days,
                    "limit": limit,
                },
            )
            ops_agent_db_query_latency_seconds.labels(
                query_name="similarity_attribute_search"
            ).observe(time.perf_counter() - query_start)
        except Exception:
            ops_agent_db_query_failures_total.labels(query_name="similarity_attribute_search").inc()
            raise

        matches: list[dict[str, Any]] = []
        for row in result.fetchall():
            row_card_id = str(row.card_id) if row.card_id is not None else ""
            row_merchant_id = str(row.merchant_id) if row.merchant_id is not None else ""
            try:
                decision_value = row.decision
            except AttributeError:
                decision_value = None
            same_card = bool(card_id and row_card_id and str(card_id) == row_card_id)
            same_merchant = bool(
                merchant_id and row_merchant_id and str(merchant_id) == row_merchant_id
            )
            counter_flags = self._counter_evidence_flags(getattr(row, "transaction_context", None))
            matches.append(
                {
                    "transaction_id": str(row.transaction_id),
                    "amount": float(row.amount) if row.amount is not None else 0.0,
                    "merchant_id": str(row.merchant_id) if row.merchant_id is not None else None,
                    "card_id": str(row.card_id) if row.card_id is not None else None,
                    "decision": str(decision_value) if decision_value is not None else None,
                    "transaction_timestamp": row.transaction_timestamp,
                    "match_type": "attribute",
                    "similarity_score": float(row.similarity_score),
                    **counter_flags,
                    "details": {
                        "same_card": same_card,
                        "same_merchant": same_merchant,
                    },
                }
            )
        return matches

    def _merge_matches(
        self, vector_matches: list[dict[str, Any]], attribute_matches: list[dict[str, Any]]
    ) -> list[dict[str, Any]]:
        merged: dict[str, dict[str, Any]] = {}
        for match in vector_matches + attribute_matches:
            txn_id = match.get("transaction_id")
            if not txn_id:
                continue
            existing = merged.get(txn_id)
            if existing is None or float(match.get("similarity_score", 0.0)) > float(
                existing.get("similarity_score", 0.0)
            ):
                merged[txn_id] = match
        return list(merged.values())
