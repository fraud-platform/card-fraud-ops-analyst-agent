"""Rule Management HTTP client for exporting rule drafts."""

import os
import time
from dataclasses import dataclass
from threading import Lock
from typing import Any

import httpx
from tenacity import AsyncRetrying, retry_if_exception_type, stop_after_attempt, wait_exponential

from app.core.config import get_settings
from app.core.tracing import get_tracing_headers


class CircuitBreaker:
    """Simple circuit breaker to prevent cascading failures.

    SECURITY: Prevents repeated calls to a failing service, protecting both
    the caller from timeout storms and the failing service from overload.
    """

    def __init__(self, failure_threshold: int = 5, recovery_timeout: float = 60.0):
        self.failure_threshold = failure_threshold
        self.recovery_timeout = recovery_timeout
        self._failure_count = 0
        self._last_failure_time = 0.0
        self._state = "closed"  # closed, open, half-open
        self._lock = Lock()

    def is_open(self) -> bool:
        """Check if circuit is open (blocking requests)."""
        with self._lock:
            if self._state == "open":
                # Check if we should transition to half-open
                if time.time() - self._last_failure_time >= self.recovery_timeout:
                    self._state = "half-open"
                    return False
                return True
            return False

    def on_success(self) -> None:
        """Record a success, reset circuit if recovering."""
        with self._lock:
            self._failure_count = 0
            if self._state == "half-open":
                self._state = "closed"

    def on_failure(self) -> None:
        """Record a failure, open circuit if threshold reached."""
        with self._lock:
            self._failure_count += 1
            self._last_failure_time = time.time()
            if self._failure_count >= self.failure_threshold:
                self._state = "open"


@dataclass
class ExportResult:
    """Result of a draft export operation."""

    success: bool
    response_id: str | None = None
    error_message: str | None = None
    status_code: int | None = None


class RuleManagementClient:
    """HTTP client for Rule Management API."""

    # SECURITY: Circuit breaker prevents cascading failures from Rule Management
    _circuit_breaker: CircuitBreaker = CircuitBreaker(
        failure_threshold=5,  # Open after 5 consecutive failures
        recovery_timeout=60.0,  # Retry after 60 seconds
    )

    def __init__(self, base_url: str | None = None, timeout: float = 30.0):
        settings = get_settings()
        self.base_url = base_url or settings.features.rule_management_base_url or ""
        self.timeout = timeout
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create async HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=self.timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    def _resolve_auth_config(self) -> tuple[str, str, str, str]:
        """Resolve M2M auth config from settings/env.

        Preference order:
        1) AUTH0_MGMT_* env vars (if present)
        2) AUTH0_* settings
        """
        settings = get_settings()
        domain = os.getenv("AUTH0_MGMT_DOMAIN") or settings.auth0.domain
        client_id = os.getenv("AUTH0_MGMT_CLIENT_ID") or settings.auth0.client_id
        client_secret = (
            os.getenv("AUTH0_MGMT_CLIENT_SECRET") or settings.auth0.client_secret.get_secret_value()
        )
        audience = settings.auth0.audience
        return domain, client_id, client_secret, audience

    async def _fetch_m2m_token(self) -> str | None:
        """Fetch service-to-service token when auth settings are available."""
        domain, client_id, client_secret, audience = self._resolve_auth_config()
        if not domain or not client_id or not client_secret or not audience:
            return None

        token_url = f"https://{domain}/oauth/token"
        client = await self._get_client()
        response = await client.post(
            token_url,
            json={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "audience": audience,
            },
            timeout=self.timeout,
        )
        response.raise_for_status()
        data = response.json() if response.content else {}
        token = data.get("access_token")
        if not token:
            raise httpx.RequestError("Auth0 token response missing access_token")
        return str(token)

    async def _build_headers(self) -> dict[str, str]:
        """Build outbound headers, adding bearer token and tracing headers."""
        headers = {"Content-Type": "application/json"}

        # Add distributed tracing headers for request correlation
        headers.update(get_tracing_headers())

        try:
            token = await self._fetch_m2m_token()
            if token:
                headers["Authorization"] = f"Bearer {token}"
        except Exception:
            return headers
        return headers

    async def export_draft(
        self,
        endpoint: str,
        payload: dict[str, Any],
    ) -> ExportResult:
        """Export a rule draft to Rule Management.

        Args:
            endpoint: Target endpoint path (e.g., /api/v1/ops-agent-drafts/import)
            payload: Rule draft payload to send

        Returns:
            ExportResult with success status and details
        """
        # SECURITY: Check circuit breaker before attempting request
        if self._circuit_breaker.is_open():
            return ExportResult(
                success=False,
                error_message="Circuit breaker is open - Rule Management service is temporarily unavailable",
            )

        if not self.base_url:
            return ExportResult(
                success=False,
                error_message="Rule Management base URL not configured",
            )

        url = f"{self.base_url.rstrip('/')}{endpoint}"

        try:
            client = await self._get_client()
            headers = await self._build_headers()

            async for attempt in AsyncRetrying(
                stop=stop_after_attempt(3),
                wait=wait_exponential(multiplier=1, min=1, max=8),
                retry=retry_if_exception_type(httpx.RequestError),
                reraise=True,
            ):
                with attempt:
                    response = await client.post(
                        url,
                        json=payload,
                        headers=headers,
                        timeout=self.timeout,
                    )
                    if response.status_code >= 500:
                        raise httpx.RequestError(
                            f"Server error: {response.status_code}",
                            request=response.request,
                        )

            if 200 <= response.status_code < 300:
                response_data = response.json() if response.content else {}
                # SECURITY: Record success for circuit breaker
                self._circuit_breaker.on_success()
                return ExportResult(
                    success=True,
                    response_id=response_data.get("id") or response_data.get("rule_id"),
                    status_code=response.status_code,
                )

            # SECURITY: Non-success response counts as failure
            self._circuit_breaker.on_failure()
            return ExportResult(
                success=False,
                error_message=f"HTTP {response.status_code}: {response.text[:200]}",
                status_code=response.status_code,
            )

        except httpx.TimeoutException as e:
            # SECURITY: Timeout counts as failure
            self._circuit_breaker.on_failure()
            return ExportResult(
                success=False,
                error_message=f"Request timeout: {str(e)}",
            )
        except httpx.RequestError as e:
            # SECURITY: Request error counts as failure
            self._circuit_breaker.on_failure()
            return ExportResult(
                success=False,
                error_message=f"Request error: {str(e)}",
            )
        except Exception as e:
            # SECURITY: Unexpected error counts as failure
            self._circuit_breaker.on_failure()
            return ExportResult(
                success=False,
                error_message=f"Unexpected error: {str(e)}",
            )
