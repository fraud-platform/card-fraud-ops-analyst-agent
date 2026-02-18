"""Extended unit tests for RuleManagementClient covering uncovered lines."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.clients.rule_management_client import RuleManagementClient

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _fake_response(
    status_code: int,
    json_data: dict | None = None,
    text: str = "",
    content: bytes = b"{}",
) -> MagicMock:
    """Build a mock httpx.Response-like object."""
    resp = MagicMock()
    resp.status_code = status_code
    resp.text = text
    resp.content = content
    resp._json_data = json_data or {}
    resp.json.return_value = json_data or {}
    resp.request = httpx.Request("POST", "http://rm-test/api/v1/import")

    def _raise_for_status():
        if status_code >= 400:
            raise httpx.HTTPStatusError("error", request=resp.request, response=resp)

    resp.raise_for_status = _raise_for_status
    return resp


# ---------------------------------------------------------------------------
# close()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_when_client_is_set_calls_aclose():
    """close() calls aclose on the underlying httpx.AsyncClient."""
    client = RuleManagementClient(base_url="http://rm")

    mock_http_client = AsyncMock()
    mock_http_client.aclose = AsyncMock(return_value=None)
    client._client = mock_http_client

    await client.close()

    mock_http_client.aclose.assert_called_once()
    assert client._client is None


@pytest.mark.asyncio
async def test_close_when_client_is_none_is_noop():
    """close() does nothing when _client is already None."""
    client = RuleManagementClient(base_url="http://rm")
    client._client = None

    # Should not raise
    await client.close()

    assert client._client is None


# ---------------------------------------------------------------------------
# _resolve_auth_config()
# ---------------------------------------------------------------------------


def test_resolve_auth_config_reads_env_vars_first(monkeypatch: pytest.MonkeyPatch):
    """_resolve_auth_config() prefers AUTH0_MGMT_* env vars over settings."""
    monkeypatch.setenv("AUTH0_MGMT_DOMAIN", "env-domain.auth0.com")
    monkeypatch.setenv("AUTH0_MGMT_CLIENT_ID", "env-client-id")
    monkeypatch.setenv("AUTH0_MGMT_CLIENT_SECRET", "env-client-secret")

    with patch("app.clients.rule_management_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.auth0.domain = "settings-domain.auth0.com"
        settings.auth0.client_id = "settings-client-id"
        settings.auth0.client_secret.get_secret_value.return_value = "settings-secret"
        settings.auth0.audience = "https://example-api"
        mock_settings.return_value = settings

        client = RuleManagementClient(base_url="http://rm")
        domain, client_id, client_secret, audience = client._resolve_auth_config()

    assert domain == "env-domain.auth0.com"
    assert client_id == "env-client-id"
    assert client_secret == "env-client-secret"
    assert audience == "https://example-api"


def test_resolve_auth_config_falls_back_to_settings(monkeypatch: pytest.MonkeyPatch):
    """_resolve_auth_config() uses settings when env vars are absent."""
    monkeypatch.delenv("AUTH0_MGMT_DOMAIN", raising=False)
    monkeypatch.delenv("AUTH0_MGMT_CLIENT_ID", raising=False)
    monkeypatch.delenv("AUTH0_MGMT_CLIENT_SECRET", raising=False)

    with patch("app.clients.rule_management_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.auth0.domain = "fallback-domain.auth0.com"
        settings.auth0.client_id = "fallback-client-id"
        settings.auth0.client_secret.get_secret_value.return_value = "fallback-secret"
        settings.auth0.audience = "https://fallback-api"
        mock_settings.return_value = settings

        client = RuleManagementClient(base_url="http://rm")
        domain, client_id, client_secret, audience = client._resolve_auth_config()

    assert domain == "fallback-domain.auth0.com"
    assert client_id == "fallback-client-id"


# ---------------------------------------------------------------------------
# _fetch_m2m_token()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_m2m_token_returns_none_when_missing_config():
    """_fetch_m2m_token() returns None when auth config is incomplete."""
    client = RuleManagementClient(base_url="http://rm")

    client._resolve_auth_config = lambda: ("", "", "", "")

    token = await client._fetch_m2m_token()

    assert token is None


@pytest.mark.asyncio
async def test_fetch_m2m_token_fetches_token_successfully():
    """_fetch_m2m_token() returns access_token from Auth0 response."""
    client = RuleManagementClient(base_url="http://rm")

    token_response = _fake_response(200, json_data={"access_token": "m2m-token-xyz"})
    token_response.raise_for_status = MagicMock(return_value=None)

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=token_response)

    client._resolve_auth_config = lambda: (
        "tenant.auth0.com",
        "client-id",
        "client-secret",
        "https://api-audience",
    )

    async def fake_get_client():
        return mock_http

    client._get_client = fake_get_client

    token = await client._fetch_m2m_token()

    assert token == "m2m-token-xyz"
    mock_http.post.assert_called_once()
    call_kwargs = mock_http.post.call_args
    assert "client_credentials" in str(call_kwargs)


@pytest.mark.asyncio
async def test_fetch_m2m_token_raises_when_missing_access_token():
    """_fetch_m2m_token() raises RequestError when response has no access_token."""
    client = RuleManagementClient(base_url="http://rm")

    token_response = _fake_response(200, json_data={"something_else": "value"})
    token_response.raise_for_status = MagicMock(return_value=None)
    token_response.content = b'{"something_else": "value"}'

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=token_response)

    client._resolve_auth_config = lambda: (
        "tenant.auth0.com",
        "client-id",
        "client-secret",
        "https://api-audience",
    )

    async def fake_get_client():
        return mock_http

    client._get_client = fake_get_client

    with pytest.raises(httpx.RequestError, match="missing access_token"):
        await client._fetch_m2m_token()


# ---------------------------------------------------------------------------
# _build_headers()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_headers_includes_bearer_token_when_available():
    """_build_headers() adds Authorization header when token fetch succeeds."""
    client = RuleManagementClient(base_url="http://rm")

    async def fake_fetch_token():
        return "bearer-abc"

    client._fetch_m2m_token = fake_fetch_token

    headers = await client._build_headers()

    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer bearer-abc"


@pytest.mark.asyncio
async def test_build_headers_returns_plain_when_token_fetch_fails():
    """_build_headers() returns plain headers when token fetch raises an exception."""
    client = RuleManagementClient(base_url="http://rm")

    async def failing_token():
        raise RuntimeError("token fetch blew up")

    client._fetch_m2m_token = failing_token

    headers = await client._build_headers()

    assert headers["Content-Type"] == "application/json"
    assert "Authorization" not in headers


@pytest.mark.asyncio
async def test_build_headers_no_authorization_when_token_is_none():
    """_build_headers() omits Authorization when _fetch_m2m_token returns None."""
    client = RuleManagementClient(base_url="http://rm")

    async def none_token():
        return None

    client._fetch_m2m_token = none_token

    headers = await client._build_headers()

    assert "Authorization" not in headers


# ---------------------------------------------------------------------------
# export_draft()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_export_draft_empty_base_url_returns_failure():
    """export_draft() returns failure ExportResult when base_url is empty."""
    with patch("app.clients.rule_management_client.get_settings") as mock_settings:
        settings = MagicMock()
        settings.features.rule_management_base_url = ""
        mock_settings.return_value = settings

        client = RuleManagementClient(base_url="")

    result = await client.export_draft("/api/v1/import", {"data": "value"})

    assert result.success is False
    assert "not configured" in (result.error_message or "")


@pytest.mark.asyncio
async def test_export_draft_success_200():
    """export_draft() returns successful ExportResult on HTTP 200."""
    client = RuleManagementClient(base_url="http://rm-service")

    success_response = _fake_response(200, json_data={"id": "draft-001"})
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=success_response)

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is True
    assert result.response_id == "draft-001"
    assert result.status_code == 200


@pytest.mark.asyncio
async def test_export_draft_success_201():
    """export_draft() returns successful ExportResult on HTTP 201."""
    client = RuleManagementClient(base_url="http://rm-service")

    success_response = _fake_response(201, json_data={"rule_id": "rule-abc"})
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=success_response)

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is True
    assert result.response_id == "rule-abc"
    assert result.status_code == 201


@pytest.mark.asyncio
async def test_export_draft_4xx_returns_failure():
    """export_draft() returns failure ExportResult on HTTP 4xx."""
    client = RuleManagementClient(base_url="http://rm-service")

    bad_response = _fake_response(422, text="Unprocessable entity")
    mock_http = AsyncMock()
    mock_http.post = AsyncMock(return_value=bad_response)

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is False
    assert result.status_code == 422
    assert "422" in (result.error_message or "")


@pytest.mark.asyncio
async def test_export_draft_timeout_returns_failure():
    """export_draft() returns failure ExportResult on TimeoutException."""
    client = RuleManagementClient(base_url="http://rm-service")

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=httpx.TimeoutException("request timed out"))

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is False
    assert "timeout" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_export_draft_request_error_returns_failure():
    """export_draft() returns failure ExportResult on RequestError (non-timeout)."""
    client = RuleManagementClient(base_url="http://rm-service")

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(
        side_effect=httpx.RequestError(
            "connection refused",
            request=httpx.Request("POST", "http://rm-service/api/v1/import"),
        )
    )

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is False
    assert result.error_message is not None


@pytest.mark.asyncio
async def test_export_draft_unexpected_exception_returns_failure():
    """export_draft() returns failure ExportResult on unexpected Exception."""
    client = RuleManagementClient(base_url="http://rm-service")

    mock_http = AsyncMock()
    mock_http.post = AsyncMock(side_effect=RuntimeError("unexpected error"))

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {"rule": "data"})

    assert result.success is False
    assert "unexpected" in (result.error_message or "").lower()


@pytest.mark.asyncio
async def test_export_draft_strips_trailing_slash_from_base_url():
    """export_draft() correctly joins base URL with trailing slash and endpoint."""
    client = RuleManagementClient(base_url="http://rm-service/")

    called_urls: list[str] = []
    ok_response = _fake_response(200, json_data={"id": "x"})

    async def capture_post(url, **kwargs):
        called_urls.append(url)
        return ok_response

    mock_http = AsyncMock()
    mock_http.post = capture_post

    async def fake_get_client():
        return mock_http

    async def fake_build_headers():
        return {"Content-Type": "application/json"}

    client._get_client = fake_get_client
    client._build_headers = fake_build_headers

    result = await client.export_draft("/api/v1/import", {})

    assert result.success is True
    assert called_urls[0] == "http://rm-service/api/v1/import"
