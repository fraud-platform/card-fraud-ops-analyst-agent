"""Similarity tool - finds similar historical fraud investigations using vector embeddings."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

import structlog
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.state import update_state
from app.core.config import get_settings
from app.core.errors import ToolPreconditionError
from app.persistence.base import row_to_dict
from app.tools._core.similarity_logic import evaluate_similarity
from app.tools.base import BaseTool
from app.utils.dataclass_utils import to_dict

if TYPE_CHECKING:
    from app.agent.state import InvestigationState
    from app.clients.embedding_client import EmbeddingClient

logger = structlog.get_logger(__name__)


class SimilarityTool(BaseTool):
    """Find similar historical fraud investigations using vector similarity search."""

    @property
    def name(self) -> str:
        return "similarity_tool"

    @property
    def description(self) -> str:
        return "Find similar historical fraud investigations using vector similarity search"

    def __init__(
        self,
        embedding_client: EmbeddingClient,
        session: AsyncSession,
    ) -> None:
        self._embedding_client = embedding_client
        self._session = session

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        if not context:
            raise ToolPreconditionError(
                "Context must be populated before similarity analysis",
                tool_name=self.name,
            )

        settings = get_settings()
        if not settings.vector_search.enabled:
            return update_state(
                state,
                similarity_results={"matches": [], "overall_score": 0.0, "skipped": True},
            )

        embedding_model = settings.vector_search.model_name
        embedding_dimension = int(settings.vector_search.dimension)
        try:
            embed_text = self._build_embed_text(context)
            embedding_response = await self._embedding_client.embed(embed_text)
            embedding_model = embedding_response.model
            embedding_dimension = len(embedding_response.embedding)
            exclude_transaction_pk_id = context.get("transaction_pk_id")
            if (
                not isinstance(exclude_transaction_pk_id, str)
                or not exclude_transaction_pk_id.strip()
            ):
                exclude_transaction_pk_id = None

            similar_rows = await self._query_similar(
                embedding_response.embedding,
                limit=settings.vector_search.search_limit,
                min_similarity=settings.vector_search.min_similarity,
                exclude_transaction_pk_id=exclude_transaction_pk_id,
            )
            result = evaluate_similarity(
                transaction=context.get("transaction", {}),
                similar_transactions=similar_rows,
            )
            result_payload = to_dict(result)
            candidate_count = len(similar_rows)
            match_count = len(result.matches)
            result_payload["vector_diagnostics"] = {
                "enabled": True,
                "embedding_model": embedding_response.model,
                "embedding_dimension": len(embedding_response.embedding),
                "candidate_count": candidate_count,
                "search_limit": settings.vector_search.search_limit,
                "min_similarity": settings.vector_search.min_similarity,
            }
            if not similar_rows:
                result_payload["vector_diagnostics"]["reason"] = (
                    "no_candidates_above_similarity_threshold"
                )
        except Exception as exc:
            # A failed similarity query can leave the shared SQLAlchemy session in
            # aborted state; rollback so downstream persistence still succeeds.
            await self._session.rollback()
            logger.warning(
                "Similarity analysis failed, returning empty result",
                investigation_id=state.get("investigation_id"),
                error=str(exc),
            )
            result_payload = {
                "matches": [],
                "overall_score": 0.0,
                "skipped": True,
                "vector_diagnostics": {
                    "enabled": True,
                    "embedding_model": embedding_model,
                    "embedding_dimension": embedding_dimension,
                    "candidate_count": 0,
                    "search_limit": settings.vector_search.search_limit,
                    "min_similarity": settings.vector_search.min_similarity,
                    "reason": "embedding_or_similarity_failed",
                    "error": str(exc)[:240],
                },
            }
            candidate_count = 0
            match_count = 0

        evidence_entry = {
            "category": "similarity_analysis",
            "tool": "similarity_tool",
            "description": (
                f"Found {match_count} similar transactions (candidates={candidate_count})"
            ),
            "data": result_payload,
        }

        return update_state(
            state,
            similarity_results=result_payload,
            evidence=[*state["evidence"], evidence_entry],
        )

    def _build_embed_text(self, context: dict[str, Any]) -> str:
        transaction = context.get("transaction", {})
        if hasattr(transaction, "__dataclass_fields__"):
            import dataclasses

            transaction = dataclasses.asdict(transaction)

        parts = [
            f"amount: {transaction.get('amount', 0)}",
            f"merchant: {transaction.get('merchant_id', 'unknown')}",
            f"currency: {transaction.get('currency', 'USD')}",
        ]
        return " | ".join(parts)

    async def _query_similar(
        self,
        embedding: list[float],
        limit: int,
        min_similarity: float,
        exclude_transaction_pk_id: str | None = None,
    ) -> list[dict[str, Any]]:
        # Use CAST(:param AS vector) instead of :param::vector — the PostgreSQL
        # :: cast operator after a named parameter confuses SQLAlchemy's parameter parser,
        # causing the parameter to not be substituted and producing a syntax error.
        query = text("""
            SELECT
                t.transaction_id::text AS transaction_id,
                1 - (e.embedding <=> CAST(:embedding AS vector)) AS similarity_score,
                t.transaction_amount AS amount,
                t.card_id,
                t.merchant_id,
                t.decision,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'3ds_verified', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS three_ds_authenticated,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'trusted_device', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS is_trusted_device,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'avs_match', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS avs_match,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'cvv_match', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS cvv_match,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'tokenized', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    WHEN lower(coalesce(t.transaction_context->>'payment_token_present', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS is_tokenized,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'cardholder_present', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS cardholder_present,
                CASE
                    WHEN lower(coalesce(t.transaction_context->>'known_merchant', '')) IN ('true', 't', '1', 'yes', 'y')
                        THEN TRUE
                    ELSE FALSE
                END AS is_known_merchant,
                e.metadata
            FROM fraud_gov.ops_agent_transaction_embeddings e
            JOIN fraud_gov.transactions t ON t.id = e.transaction_id
            WHERE 1 - (e.embedding <=> CAST(:embedding AS vector)) >= :min_sim
              AND (
                    CAST(:exclude_txn_pk AS text) IS NULL
                    OR e.transaction_id::text <> CAST(:exclude_txn_pk AS text)
              )
            ORDER BY e.embedding <=> CAST(:embedding AS vector)
            LIMIT :limit
        """)
        result = await self._session.execute(
            query,
            {
                "embedding": str(embedding),
                "min_sim": min_similarity,
                "limit": limit,
                "exclude_txn_pk": exclude_transaction_pk_id,
            },
        )
        return [row_to_dict(r) for r in result.fetchall()]
