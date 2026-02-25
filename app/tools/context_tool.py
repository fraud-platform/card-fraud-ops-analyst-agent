"""Context tool - retrieves transaction context from TM API (TDD-007).

Uses the overview endpoint to fetch transaction + review + notes + case + rules
in a single call, then parallel-fetches card and merchant history.
"""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING, Any

import structlog

from app.agent.state import update_state
from app.tools._core.context_logic import assemble_context
from app.tools.base import BaseTool

if TYPE_CHECKING:
    from app.agent.state import InvestigationState
    from app.clients.tm_client import TMClient

logger = structlog.get_logger(__name__)


class ContextTool(BaseTool):
    """Retrieve transaction details, card history, and merchant context from TM API."""

    @property
    def name(self) -> str:
        return "context_tool"

    @property
    def description(self) -> str:
        return (
            "Retrieve transaction details, card history, and merchant context "
            "from Transaction Management API"
        )

    def __init__(self, tm_client: TMClient) -> None:
        self._tm_client = tm_client

    async def execute(self, state: InvestigationState) -> InvestigationState:
        # Skip TM calls on resume if context already populated (TDD-007 §9.8)
        if state.get("context") and state["context"].get("transaction"):
            logger.info(
                "Context already populated, skipping TM API calls",
                investigation_id=state["investigation_id"],
            )
            return state

        transaction_id = state["transaction_id"]

        # Single overview call replaces 5 old ContextReader methods (TDD-007 §2.2)
        overview = await self._tm_client.get_transaction_overview(
            transaction_id, include_rules=True
        )

        transaction = overview.get("transaction", {})
        card_id = transaction.get("card_id")
        merchant_id = transaction.get("merchant_id")

        # Parallel fetch card + merchant history (TDD-007 §7)
        card_task = (
            self._tm_client.get_card_history(card_id, hours_back=72)
            if card_id
            else self._empty_list()
        )
        merchant_task = (
            self._tm_client.get_merchant_history(merchant_id, hours_back=72)
            if merchant_id
            else self._empty_list()
        )

        results = await asyncio.gather(card_task, merchant_task, return_exceptions=True)

        card_history = self._extract_result(results[0], "card history", card_id=card_id)
        merchant_history = self._extract_result(
            results[1], "merchant history", merchant_id=merchant_id
        )

        # assemble_context handles window computation internally
        context = assemble_context(
            transaction=transaction,
            card_history=card_history,
            merchant_history=merchant_history,
            rule_matches=overview.get("matched_rules", []),
            reviews=[overview["review"]] if overview.get("review") else [],
            notes=overview.get("notes", []),
            case=overview.get("case"),
        )

        logger.info(
            "Context assembled",
            investigation_id=state["investigation_id"],
            transaction_id=transaction_id,
            card_history_count=len(card_history),
            merchant_history_count=len(merchant_history),
            rule_match_count=len(overview.get("matched_rules", [])),
        )

        return update_state(state, context=context)

    @staticmethod
    async def _empty_list() -> list:
        """Return empty list for missing IDs."""
        return []

    @staticmethod
    def _extract_result(result: Any, label: str, **log_context: Any) -> list[dict]:
        """Extract a list result from asyncio.gather, logging exceptions."""
        if isinstance(result, list):
            return result
        if isinstance(result, Exception):
            logger.warning(f"Failed to fetch {label}", error=str(result), **log_context)
        return []
