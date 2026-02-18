"""Context builder - DB-bound module that reads TM tables and calls core."""

import asyncio
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.context_builder_core import assemble_context
from app.persistence.context_reader import ContextReader


class ContextBuilder:
    """DB-bound context builder that reads TM tables and assembles context."""

    def __init__(self, session: AsyncSession):
        self.reader = ContextReader(session)

    async def build(self, transaction_id: str) -> dict[str, Any]:
        """Build complete context for a transaction."""
        transaction = await self.reader.get_transaction(transaction_id)

        if transaction is None:
            raise ValueError(f"Transaction not found: {transaction_id}")

        card_id = transaction.get("card_id")
        merchant_id = transaction.get("merchant_id")

        # Parallelize independent queries for better performance
        queries = [
            self.reader.get_transaction_rule_matches(transaction_id),
            self.reader.get_transaction_reviews(transaction_id),
            self.reader.get_analyst_notes(transaction_id),
            self.reader.get_transaction_case(transaction_id),
        ]

        if card_id:
            queries.append(self.reader.get_card_history(card_id, hours_back=72))
        if merchant_id:
            queries.append(self.reader.get_merchant_history(merchant_id, hours_back=72))

        # SECURITY: Check for exceptions in gather results to avoid silent failures
        results = await asyncio.gather(*queries, return_exceptions=True)

        # Extract results, checking for exceptions
        def unwrap(result: Any, index: int) -> Any:
            if isinstance(result, Exception):
                raise RuntimeError(f"Query {index} failed: {result}") from result
            return result

        rule_matches = unwrap(results[0], 0)
        reviews = unwrap(results[1], 1)
        notes = unwrap(results[2], 2)
        case = unwrap(results[3], 3)
        card_history = unwrap(results[4], 4) if card_id else []
        merchant_history = unwrap(results[5], 5) if merchant_id else []

        context = assemble_context(
            transaction=transaction,
            card_history=card_history or [],
            merchant_history=merchant_history or [],
            rule_matches=rule_matches,
            reviews=reviews,
            notes=notes,
            case=case,
        )

        return context
