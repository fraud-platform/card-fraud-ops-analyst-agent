"""Link analysis tool - detects coordinated card/merchant activity from history windows."""

from __future__ import annotations

import asyncio
from typing import TYPE_CHECKING

import structlog

from app.core.errors import ToolPreconditionError
from app.tools._core.link_analysis_logic import (
    augment_link_analysis_with_neighborhoods,
    run_link_analysis,
)
from app.tools.base import BaseTool
from app.tools.evidence import EvidenceEntry, append_evidence
from app.utils.dataclass_utils import to_dict

if TYPE_CHECKING:
    from app.agent.state import InvestigationState
    from app.clients.tm_client import TMClient

logger = structlog.get_logger(__name__)


class LinkAnalysisTool(BaseTool):
    """Detect coordinated activity using card fan-out and merchant fan-in signals."""

    def __init__(self, tm_client: TMClient | None = None) -> None:
        self._tm_client = tm_client

    @property
    def name(self) -> str:
        return "link_analysis_tool"

    @property
    def description(self) -> str:
        return (
            "Run link analysis on card and merchant history windows for coordinated activity "
            "(fan-out/fan-in/ring signatures)"
        )

    async def execute(self, state: InvestigationState) -> InvestigationState:
        context = state["context"]
        if not context:
            raise ToolPreconditionError(
                "Context must be populated before link analysis",
                tool_name=self.name,
            )

        transaction = to_dict(context.get("transaction", {}))
        card_history = context.get("card_history", [])
        merchant_history = context.get("merchant_history", [])

        result = run_link_analysis(
            transaction=transaction,
            card_history=card_history if isinstance(card_history, list) else [],
            merchant_history=merchant_history if isinstance(merchant_history, list) else [],
        )

        tm_enriched = await self._enrich_with_tm_neighborhoods(context, transaction)
        result = augment_link_analysis_with_neighborhoods(
            result,
            current_transaction_id=str(transaction.get("transaction_id", "") or ""),
            ip_neighbors=tm_enriched["ip_neighbors"],
            device_neighbors=tm_enriched["device_neighbors"],
            fingerprint_neighbors=tm_enriched["fingerprint_neighbors"],
        )

        evidence_entry = EvidenceEntry(
            category="link_analysis",
            tool=self.name,
            description=(
                f"Detected {len(result.get('signals', []))} link-analysis signals "
                f"(overall_score={float(result.get('overall_score', 0.0)):.2f})"
            ),
            data=result,
        )

        return append_evidence(
            state,
            evidence_entry,
            link_analysis_results=result,
        )

    async def _enrich_with_tm_neighborhoods(
        self,
        context: dict,
        transaction: dict,
    ) -> dict[str, list[dict]]:
        if self._tm_client is None:
            return {
                "ip_neighbors": [],
                "device_neighbors": [],
                "fingerprint_neighbors": [],
            }

        features = context.get("features", {}) if isinstance(context.get("features"), dict) else {}
        tx_context = (
            context.get("transaction_context", {})
            if isinstance(context.get("transaction_context"), dict)
            else {}
        )
        device_ctx = (
            tx_context.get("device", {}) if isinstance(tx_context.get("device"), dict) else {}
        )

        ip_address = self._first_non_empty_str(
            features.get("ip_address"),
            tx_context.get("ip_address"),
            transaction.get("ip_address"),
        )
        device_id = self._first_non_empty_str(
            features.get("device_id"),
            device_ctx.get("device_id"),
            transaction.get("device_id"),
        )
        device_fingerprint_hash = self._first_non_empty_str(
            features.get("device_fingerprint_hash"),
            device_ctx.get("device_fingerprint_hash"),
            transaction.get("device_fingerprint_hash"),
        )

        tasks = [
            self._fetch_neighbors("ip", ip_address),
            self._fetch_neighbors("device", device_id),
            self._fetch_neighbors("fingerprint", device_fingerprint_hash),
        ]
        ip_neighbors, device_neighbors, fingerprint_neighbors = await asyncio.gather(*tasks)

        return {
            "ip_neighbors": ip_neighbors,
            "device_neighbors": device_neighbors,
            "fingerprint_neighbors": fingerprint_neighbors,
        }

    async def _fetch_neighbors(self, kind: str, identifier: str | None) -> list[dict]:
        if not identifier or self._tm_client is None:
            return []

        try:
            if kind == "ip":
                result = await self._tm_client.get_ip_neighborhood(identifier)
            elif kind == "device":
                result = await self._tm_client.get_device_neighborhood(identifier)
            else:
                result = await self._tm_client.get_device_fingerprint_neighborhood(identifier)
            return [item for item in result if isinstance(item, dict)]
        except Exception as exc:
            logger.warning(
                "LinkAnalysisTool neighborhood fetch failed",
                kind=kind,
                error=str(exc),
            )
            return []

    @staticmethod
    def _first_non_empty_str(*values: object) -> str | None:
        for value in values:
            if isinstance(value, str):
                trimmed = value.strip()
                if trimmed:
                    return trimmed
        return None
