"""Transaction Management API client.

Implements TDD-007: get_transaction_overview, get_card_history,
get_merchant_history, health_check with field remapping, auto-pagination,
retry (tenacity), and circuit breaker.
"""

from __future__ import annotations

import time
from datetime import timedelta
from typing import Any

import httpx
import structlog
from tenacity import (
    retry,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential,
)

from app.core.config import TMClientConfig
from app.core.metrics import (
    ops_agent_dependency_failures_total,
    ops_agent_tm_api_latency_seconds,
    ops_agent_tm_api_requests_total,
)
from app.core.tracing import get_tracing_headers
from app.utils.clock import utc_now

logger = structlog.get_logger(__name__)

# ---------------------------------------------------------------------------
# Field maps: TM API field names → internal agent field names (TDD-007 §3.6)
# ---------------------------------------------------------------------------

TRANSACTION_FIELD_MAP: dict[str, str] = {
    "transaction_amount": "amount",
    "transaction_currency": "currency",
    "merchant_category_code": "merchant_category",
    "card_last4": "card_last_four",
    "decision": "status",
    "decision_reason": "decline_reason",
    "decision_score": "fraud_score",
}

RULE_MATCH_FIELD_MAP: dict[str, str] = {
    "evaluated_at": "triggered_at",
    "rule_action": "action",
    "match_score": "score",
    "rule_output": "metadata",
}

REVIEW_FIELD_MAP: dict[str, str] = {
    "assigned_analyst_id": "reviewed_by",
    "first_reviewed_at": "reviewed_at",
    "resolution_code": "decision",
    "resolution_notes": "notes",
}

NOTE_FIELD_MAP: dict[str, str] = {
    "note_content": "note_text",
    "analyst_id": "created_by",
}

CASE_FIELD_MAP: dict[str, str] = {
    "case_number": "case_id",
    "case_status": "status",
    "assigned_analyst_id": "assigned_to",
    "risk_level": "priority",
}

# Max pages to auto-paginate (TDD-007 §4.4: max 3 pages × 500 = 1500 txns)
_MAX_PAGES = 3
_PAGE_SIZE = 500


def _remap(data: dict[str, Any], field_map: dict[str, str]) -> dict[str, Any]:
    """Translate TM field names to internal agent field names."""
    result: dict[str, Any] = {}
    for key, value in data.items():
        mapped_key = field_map.get(key, key)
        result[mapped_key] = value
    return result


class TMClient:
    """HTTP client for Transaction Management API (TDD-007).

    Uses TMClientConfig for construction. Provides:
    - get_transaction_overview() — single call replaces 5 ContextReader methods
    - get_card_history() — paginated card history
    - get_merchant_history() — paginated merchant history
    - health_check() — TM API liveness

    Includes in-memory caching for card/merchant history to reduce repeated calls.
    """

    _CACHE_TTL_SECONDS = 300  # 5 minutes

    def __init__(self, config: TMClientConfig) -> None:
        self._base_url = config.base_url.rstrip("/")
        self._timeout = config.timeout_seconds
        self._retry_count = config.retry_count
        self._client: httpx.AsyncClient | None = None

        # Circuit breaker state
        self._cb_threshold = config.circuit_breaker_threshold
        self._cb_timeout = config.circuit_breaker_timeout
        self._consecutive_failures = 0
        self._circuit_open_until: float = 0.0

        # Simple in-memory cache for card/merchant history
        self._history_cache: dict[str, tuple[float, list[dict[str, Any]]]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self._timeout)
        return self._client

    async def close(self) -> None:
        """Close the underlying HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None
        self._history_cache.clear()

    def _get_cached_history(self, cache_key: str) -> list[dict[str, Any]] | None:
        """Get cached history if still valid."""
        if cache_key in self._history_cache:
            cached_time, cached_data = self._history_cache[cache_key]
            if time.time() - cached_time < self._CACHE_TTL_SECONDS:
                return cached_data
        return None

    def _set_cached_history(self, cache_key: str, data: list[dict[str, Any]]) -> None:
        """Cache history data."""
        self._history_cache[cache_key] = (time.time(), data)

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def get_transaction_overview(
        self,
        transaction_id: str,
        *,
        include_rules: bool = True,
    ) -> dict[str, Any]:
        """GET /api/v1/transactions/{id}/overview?include_rules=true

        Returns remapped overview with transaction, review, notes, case,
        matched_rules. Replaces 5 old ContextReader methods.
        """
        params: dict[str, Any] = {}
        if include_rules:
            params["include_rules"] = "true"

        data = await self._request(
            "GET",
            f"/api/v1/transactions/{transaction_id}/overview",
            params=params or None,
        )
        if not isinstance(data, dict):
            return {}

        result: dict[str, Any] = {}

        # Remap transaction fields
        if txn := data.get("transaction"):
            result["transaction"] = _remap(txn, TRANSACTION_FIELD_MAP) if txn else {}
        else:
            result["transaction"] = {}

        # Remap review
        review = data.get("review")
        result["review"] = _remap(review, REVIEW_FIELD_MAP) if review else None

        # Remap notes
        notes = data.get("notes") or []
        result["notes"] = [_remap(n, NOTE_FIELD_MAP) for n in notes]

        # Remap case
        case = data.get("case")
        result["case"] = _remap(case, CASE_FIELD_MAP) if case else None

        # Remap rule matches
        rules = data.get("matched_rules") or []
        result["matched_rules"] = [_remap(r, RULE_MATCH_FIELD_MAP) for r in rules]

        result["last_activity_at"] = data.get("last_activity_at")

        return result

    async def get_card_history(
        self,
        card_id: str,
        *,
        hours_back: int = 72,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/transactions?card_id=X&from_date=Y&page_size=500

        Auto-paginates up to 3 pages (1500 transactions max).
        Results are cached for 5 minutes to reduce repeated calls.
        """
        cache_key = f"card:{card_id}:{hours_back}:{from_date or 'default'}"
        cached = self._get_cached_history(cache_key)
        if cached is not None:
            return cached

        if from_date is None:
            cutoff = utc_now() - timedelta(hours=hours_back)
            from_date = cutoff.isoformat()

        result = await self._paginated_list(
            params={"card_id": card_id, "from_date": from_date, "page_size": _PAGE_SIZE},
        )
        self._set_cached_history(cache_key, result)
        return result

    async def get_merchant_history(
        self,
        merchant_id: str,
        *,
        hours_back: int = 72,
        from_date: str | None = None,
    ) -> list[dict[str, Any]]:
        """GET /api/v1/transactions?merchant_id=X&from_date=Y&page_size=500

        Auto-paginates up to 3 pages (1500 transactions max).
        Results are cached for 5 minutes to reduce repeated calls.
        """
        cache_key = f"merchant:{merchant_id}:{hours_back}:{from_date or 'default'}"
        cached = self._get_cached_history(cache_key)
        if cached is not None:
            return cached

        if from_date is None:
            cutoff = utc_now() - timedelta(hours=hours_back)
            from_date = cutoff.isoformat()

        result = await self._paginated_list(
            params={"merchant_id": merchant_id, "from_date": from_date, "page_size": _PAGE_SIZE},
        )
        self._set_cached_history(cache_key, result)
        return result

    async def health_check(self) -> bool:
        """GET /api/v1/health — returns True if TM API is reachable."""
        try:
            await self._request("GET", "/api/v1/health")
            return True
        except Exception:
            return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    async def _paginated_list(
        self,
        params: dict[str, Any],
    ) -> list[dict[str, Any]]:
        """Auto-paginate GET /api/v1/transactions with cursor follow."""
        all_items: list[dict[str, Any]] = []

        for _page in range(_MAX_PAGES):
            data = await self._request("GET", "/api/v1/transactions", params=params)
            if not isinstance(data, dict):
                break

            items = data.get("items") or data.get("data") or []
            if isinstance(data, list):
                items = data

            remapped = [_remap(item, TRANSACTION_FIELD_MAP) for item in items]
            all_items.extend(remapped)

            # Follow cursor if present
            cursor = data.get("next_cursor") or data.get("cursor")
            if not cursor or len(items) < _PAGE_SIZE:
                break
            params = {**params, "cursor": cursor}

        return all_items

    async def _request(
        self,
        method: str,
        path: str,
        params: dict[str, Any] | None = None,
    ) -> dict[str, Any] | list[dict[str, Any]]:
        """Make HTTP request with tracing, metrics, retry, circuit breaker."""
        # Circuit breaker: fail fast if circuit is open
        if self._consecutive_failures >= self._cb_threshold:
            if time.monotonic() < self._circuit_open_until:
                logger.warning(
                    "TM API circuit breaker open, failing fast",
                    path=path,
                    failures=self._consecutive_failures,
                )
                ops_agent_dependency_failures_total.labels(dependency="tm_api").inc()
                raise httpx.ConnectError(f"Circuit breaker open for {path}")
            # Half-open: allow one request through
            logger.info("TM API circuit breaker half-open, attempting request", path=path)

        client = await self._get_client()
        headers = get_tracing_headers()
        url = f"{self._base_url}{path}"
        started = time.perf_counter()

        try:
            response = await self._request_with_retry(client, method, url, headers, params)
            elapsed = time.perf_counter() - started

            ops_agent_tm_api_latency_seconds.labels(endpoint=path).observe(elapsed)
            ops_agent_tm_api_requests_total.labels(
                endpoint=path, status_code=str(response.status_code)
            ).inc()

            response.raise_for_status()

            # Reset circuit breaker on success
            self._consecutive_failures = 0

            logger.debug(
                "TM API request succeeded",
                method=method,
                path=path,
                status_code=response.status_code,
                elapsed_ms=round(elapsed * 1000, 1),
            )

            return response.json()

        except Exception as exc:
            elapsed = time.perf_counter() - started
            self._consecutive_failures += 1

            if self._consecutive_failures >= self._cb_threshold:
                self._circuit_open_until = time.monotonic() + self._cb_timeout
                logger.error(
                    "TM API circuit breaker tripped",
                    path=path,
                    failures=self._consecutive_failures,
                    timeout_seconds=self._cb_timeout,
                )

            ops_agent_dependency_failures_total.labels(dependency="tm_api").inc()
            logger.error(
                "TM API request failed",
                method=method,
                path=path,
                elapsed_ms=round(elapsed * 1000, 1),
                error=str(exc),
            )
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=0.5, min=0.5, max=5),
        retry=retry_if_exception_type((httpx.ConnectError, httpx.ConnectTimeout)),
        reraise=True,
    )
    async def _request_with_retry(
        self,
        client: httpx.AsyncClient,
        method: str,
        url: str,
        headers: dict[str, str],
        params: dict[str, Any] | None,
    ) -> httpx.Response:
        """Execute HTTP request with tenacity retry on connection failures."""
        return await client.request(method, url, headers=headers, params=params)
