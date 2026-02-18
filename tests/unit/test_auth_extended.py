"""Extended unit tests for app.core.auth (JWKS fetch, token verification, scope checks)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from jose import JWTError

import app.core.auth as auth_module
from app.core.auth import (
    OPS_AGENT_ADMIN,
    OPS_AGENT_READ,
    OPS_AGENT_RUN,
    AuthenticatedUser,
    close_async_http_client,
    fetch_jwks,
    get_async_http_client,
    get_current_user,
    require_scope,
    verify_token_async,
)
from app.core.config import AppEnvironment
from app.core.errors import ForbiddenError, ValidationError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _reset_http_client():
    """Reset the module-level _http_client to None between tests."""
    auth_module._http_client = None


def _reset_jwks_cache():
    """Reset the JWKS cache between tests."""
    auth_module._jwks_cache = None
    auth_module._cache_time = None


# ---------------------------------------------------------------------------
# get_async_http_client()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_async_http_client_creates_new_when_none():
    """get_async_http_client() creates a new client when none exists."""
    _reset_http_client()

    client = await get_async_http_client()

    assert client is not None
    assert isinstance(client, httpx.AsyncClient)

    # Cleanup
    await client.aclose()
    _reset_http_client()


@pytest.mark.asyncio
async def test_get_async_http_client_reuses_existing_open_client():
    """get_async_http_client() returns the same client when it is still open."""
    _reset_http_client()

    client1 = await get_async_http_client()
    client2 = await get_async_http_client()

    assert client1 is client2

    await client1.aclose()
    _reset_http_client()


@pytest.mark.asyncio
async def test_get_async_http_client_creates_new_when_closed():
    """get_async_http_client() creates a fresh client when the existing one is closed."""
    _reset_http_client()

    client1 = await get_async_http_client()
    await client1.aclose()
    # _http_client still holds the closed reference

    client2 = await get_async_http_client()
    assert client2 is not client1
    assert not client2.is_closed

    await client2.aclose()
    _reset_http_client()


# ---------------------------------------------------------------------------
# close_async_http_client()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_close_async_http_client_closes_open_client():
    """close_async_http_client() closes the client and sets module var to None."""
    _reset_http_client()

    # Create a real client and store it in the module
    auth_module._http_client = httpx.AsyncClient()

    await close_async_http_client()

    assert auth_module._http_client is None


@pytest.mark.asyncio
async def test_close_async_http_client_when_none_is_noop():
    """close_async_http_client() does nothing when client is already None."""
    _reset_http_client()
    auth_module._http_client = None

    # Should not raise
    await close_async_http_client()

    assert auth_module._http_client is None


# ---------------------------------------------------------------------------
# fetch_jwks()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_fetch_jwks_fetches_from_url_and_caches():
    """fetch_jwks() fetches from the JWKS URL and stores result in cache."""
    _reset_jwks_cache()
    _reset_http_client()

    jwks_data = {"keys": [{"kid": "key-1", "kty": "RSA", "n": "abc", "e": "AQAB", "use": "sig"}]}

    mock_response = MagicMock()
    mock_response.json.return_value = jwks_data
    mock_response.raise_for_status = MagicMock(return_value=None)

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with (
        patch("app.core.auth.get_async_http_client", return_value=mock_client),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.jwks_cache_ttl = 3600
        settings.auth0.jwks_url = "https://example.auth0.com/.well-known/jwks.json"
        mock_settings.return_value = settings

        result = await fetch_jwks()

    assert result == jwks_data
    assert auth_module._jwks_cache == jwks_data
    _reset_jwks_cache()


@pytest.mark.asyncio
async def test_fetch_jwks_returns_cached_within_ttl():
    """fetch_jwks() returns cached data without making an HTTP call when within TTL."""
    jwks_data = {"keys": [{"kid": "cached-key"}]}
    auth_module._jwks_cache = jwks_data
    auth_module._cache_time = datetime.now(UTC)  # just cached

    mock_client = AsyncMock()

    with (
        patch("app.core.auth.get_async_http_client", return_value=mock_client),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.jwks_cache_ttl = 3600
        settings.auth0.jwks_url = "https://example.auth0.com/.well-known/jwks.json"
        mock_settings.return_value = settings

        result = await fetch_jwks()

    # No HTTP call should have been made
    mock_client.get.assert_not_called()
    assert result == jwks_data
    _reset_jwks_cache()


@pytest.mark.asyncio
async def test_fetch_jwks_uses_stale_cache_on_http_error():
    """fetch_jwks() returns stale cache when HTTP call fails."""
    stale_jwks = {"keys": [{"kid": "stale-key"}]}
    auth_module._jwks_cache = stale_jwks
    # Cache is expired (set 2 hours ago)
    auth_module._cache_time = datetime.now(UTC) - timedelta(hours=2)

    # raise_for_status must be a plain (non-async) callable since auth.py calls it without await
    mock_response = MagicMock()
    mock_response.raise_for_status.side_effect = httpx.HTTPStatusError(
        "503", request=MagicMock(), response=MagicMock()
    )

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(return_value=mock_response)

    with (
        patch("app.core.auth.get_async_http_client", return_value=mock_client),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.jwks_cache_ttl = 3600
        settings.auth0.jwks_url = "https://example.auth0.com/.well-known/jwks.json"
        mock_settings.return_value = settings

        result = await fetch_jwks()

    assert result == stale_jwks
    _reset_jwks_cache()


@pytest.mark.asyncio
async def test_fetch_jwks_raises_validation_error_when_no_cache():
    """fetch_jwks() raises ValidationError when HTTP fails and no cache available."""
    _reset_jwks_cache()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with (
        patch("app.core.auth.get_async_http_client", return_value=mock_client),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.jwks_cache_ttl = 3600
        settings.auth0.jwks_url = "https://example.auth0.com/.well-known/jwks.json"
        mock_settings.return_value = settings

        with pytest.raises(ValidationError, match="authentication service unavailable"):
            await fetch_jwks()

    _reset_jwks_cache()


# ---------------------------------------------------------------------------
# verify_token_async()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_async_happy_path():
    """verify_token_async() decodes and returns the JWT payload on success."""
    jwks_data = {
        "keys": [
            {
                "kid": "key-abc",
                "kty": "RSA",
                "use": "sig",
                "n": "test-n",
                "e": "AQAB",
            }
        ]
    }
    expected_payload = {
        "sub": "auth0|user123",
        "email": "user@example.com",
        "permissions": [OPS_AGENT_READ],
        "exp": 9999999999,
    }

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", return_value=expected_payload),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.algorithms_list = ["RS256"]
        settings.auth0.audience = "https://fraud-ops-analyst-agent-api"
        settings.auth0.issuer_url = "https://dev-xxx.us.auth0.com/"
        mock_settings.return_value = settings

        result = await verify_token_async("some.jwt.token")

    assert result["sub"] == "auth0|user123"
    assert result["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_verify_token_async_raises_validation_error_on_expired():
    """verify_token_async() raises ValidationError on ExpiredSignatureError."""
    from jose.exceptions import ExpiredSignatureError

    jwks_data = {"keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "x", "e": "y"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=ExpiredSignatureError("expired")),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.algorithms_list = ["RS256"]
        settings.auth0.audience = "https://fraud-ops-analyst-agent-api"
        settings.auth0.issuer_url = "https://dev-xxx.us.auth0.com/"
        mock_settings.return_value = settings

        with pytest.raises(ValidationError, match="Invalid or expired token"):
            await verify_token_async("expired.jwt.token")


@pytest.mark.asyncio
async def test_verify_token_async_raises_validation_error_on_jwt_error():
    """verify_token_async() raises ValidationError on general JWTError."""
    jwks_data = {"keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "x", "e": "y"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=JWTError("bad signature")),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.algorithms_list = ["RS256"]
        settings.auth0.audience = "https://fraud-ops-analyst-agent-api"
        settings.auth0.issuer_url = "https://dev-xxx.us.auth0.com/"
        mock_settings.return_value = settings

        with pytest.raises(ValidationError, match="Invalid or expired token"):
            await verify_token_async("bad.jwt.token")


@pytest.mark.asyncio
async def test_verify_token_async_raises_when_no_matching_key():
    """verify_token_async() raises ValidationError when kid is not in JWKS."""
    jwks_data = {"keys": [{"kid": "different-kid", "kty": "RSA", "use": "sig"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "missing-kid"}),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        settings = MagicMock()
        settings.auth0.algorithms_list = ["RS256"]
        settings.auth0.audience = "https://fraud-ops-analyst-agent-api"
        settings.auth0.issuer_url = "https://dev-xxx.us.auth0.com/"
        mock_settings.return_value = settings

        with pytest.raises(ValidationError, match="Invalid or expired token"):
            await verify_token_async("unknown.kid.token")


# ---------------------------------------------------------------------------
# get_current_user()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_skip_jwt_returns_bypass_user():
    """get_current_user() returns bypass user when skip_jwt_validation=True."""
    with patch("app.core.auth.get_settings") as mock_settings:
        settings = MagicMock()
        settings.security.skip_jwt_validation = True
        settings.app.env = AppEnvironment.LOCAL
        mock_settings.return_value = settings

        user = await get_current_user(credentials=None)

    assert user.user_id == "local-dev-user"
    assert user.has_permission(OPS_AGENT_ADMIN)
    assert user.has_permission(OPS_AGENT_READ)


@pytest.mark.asyncio
async def test_get_current_user_skip_jwt_rejected_outside_local():
    """get_current_user() rejects bypass in non-local environments."""
    with patch("app.core.auth.get_settings") as mock_settings:
        settings = MagicMock()
        settings.security.skip_jwt_validation = True
        settings.app.env = AppEnvironment.TEST
        mock_settings.return_value = settings

        with pytest.raises(
            ValidationError, match="JWT bypass is only allowed in local environment"
        ):
            await get_current_user(credentials=None)


@pytest.mark.asyncio
async def test_get_current_user_with_none_credentials_raises_validation_error():
    """get_current_user() raises ValidationError when credentials=None and JWT required."""
    with patch("app.core.auth.get_settings") as mock_settings:
        settings = MagicMock()
        settings.security.skip_jwt_validation = False
        mock_settings.return_value = settings

        with pytest.raises(ValidationError, match="Missing authorization header"):
            await get_current_user(credentials=None)


@pytest.mark.asyncio
async def test_get_current_user_with_valid_credentials():
    """get_current_user() builds AuthenticatedUser from decoded payload."""
    mock_credentials = MagicMock()
    mock_credentials.credentials = "valid.jwt.token"

    decoded_payload = {
        "sub": "auth0|abc123",
        "email": "analyst@example.com",
        "name": "Fraud Analyst",
        "permissions": [OPS_AGENT_READ, OPS_AGENT_RUN],
    }

    with (
        patch("app.core.auth.get_settings") as mock_settings,
        patch("app.core.auth.verify_token_async", new_callable=AsyncMock) as mock_verify,
    ):
        settings = MagicMock()
        settings.security.skip_jwt_validation = False
        mock_settings.return_value = settings
        mock_verify.return_value = decoded_payload

        user = await get_current_user(credentials=mock_credentials)

    assert user.user_id == "auth0|abc123"
    assert user.email == "analyst@example.com"
    assert user.name == "Fraud Analyst"
    assert user.has_permission(OPS_AGENT_READ)
    assert user.has_permission(OPS_AGENT_RUN)
    assert not user.has_permission(OPS_AGENT_ADMIN)


# ---------------------------------------------------------------------------
# require_scope()
# ---------------------------------------------------------------------------


def test_require_scope_denies_user_without_permission():
    """require_scope() raises ForbiddenError when user lacks the required scope."""
    user = AuthenticatedUser(
        user_id="user-no-run",
        email="limited@example.com",
        permissions=[OPS_AGENT_READ],  # only read, not run
    )

    scope_checker = require_scope(OPS_AGENT_RUN)

    with pytest.raises(ForbiddenError, match="Insufficient permissions"):
        scope_checker(user=user)


def test_require_scope_allows_user_with_permission():
    """require_scope() returns the user when they have the required scope."""
    user = AuthenticatedUser(
        user_id="user-with-run",
        email="analyst@example.com",
        permissions=[OPS_AGENT_READ, OPS_AGENT_RUN],
    )

    scope_checker = require_scope(OPS_AGENT_RUN)
    result = scope_checker(user=user)

    assert result is user


def test_require_scope_admin_allows_all():
    """require_scope() returns admin user for any scope check."""
    admin_user = AuthenticatedUser(
        user_id="admin-user",
        permissions=[OPS_AGENT_ADMIN, OPS_AGENT_READ, OPS_AGENT_RUN],
    )

    for scope in [OPS_AGENT_READ, OPS_AGENT_RUN, OPS_AGENT_ADMIN]:
        scope_checker = require_scope(scope)
        result = scope_checker(user=admin_user)
        assert result is admin_user


def test_require_scope_forbidden_error_includes_required_scope():
    """ForbiddenError raised by require_scope() includes the required_scope in details."""
    user = AuthenticatedUser(user_id="u1", permissions=[])
    scope_checker = require_scope(OPS_AGENT_ADMIN)

    with pytest.raises(ForbiddenError) as exc_info:
        scope_checker(user=user)

    error = exc_info.value
    assert error.details is not None
    assert error.details.get("required_scope") == OPS_AGENT_ADMIN
