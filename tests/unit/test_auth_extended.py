"""Extended unit tests for app.core.auth (JWKS fetch, token verification, scope checks)."""

from datetime import UTC, datetime, timedelta
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest
from jose import JWTError

import app.core.auth as auth_module
from app.core.auth import (
    FRAUD_ANALYST,
    OPS_AGENT_ACK,
    OPS_AGENT_ADMIN,
    OPS_AGENT_READ,
    OPS_AGENT_RUN,
    PLATFORM_ADMIN,
    AuthenticatedUser,
    close_async_http_client,
    fetch_jwks,
    get_async_http_client,
    get_current_user,
    get_user_permissions,
    get_user_roles,
    require_scope,
    verify_token_async,
)
from app.core.config import AppEnvironment
from app.core.errors import ForbiddenError, UnauthorizedError

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


def _mock_settings(**overrides):
    """Build a mock settings object with sensible Auth0 defaults."""
    settings = MagicMock()
    settings.auth0.algorithms_list = overrides.get("algorithms_list", ["RS256"])
    settings.auth0.audience = overrides.get("audience", "https://fraud-ops-analyst-agent-api")
    settings.auth0.user_audience = overrides.get("user_audience", "https://fraud-governance-api")
    settings.auth0.issuer_url = overrides.get("issuer_url", "https://dev-xxx.us.auth0.com/")
    settings.auth0.jwks_url = overrides.get(
        "jwks_url", "https://dev-xxx.us.auth0.com/.well-known/jwks.json"
    )
    settings.auth0.jwks_cache_ttl = overrides.get("jwks_cache_ttl", 3600)
    settings.auth0.accepted_audiences = overrides.get("accepted_audiences", None)
    settings.security.skip_jwt_validation = overrides.get("skip_jwt_validation", False)
    settings.security.sanitize_errors = overrides.get("sanitize_errors", False)
    settings.app.env = overrides.get("app_env", AppEnvironment.LOCAL)
    return settings


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
        mock_settings.return_value = _mock_settings()

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
        mock_settings.return_value = _mock_settings()

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
        mock_settings.return_value = _mock_settings()

        result = await fetch_jwks()

    assert result == stale_jwks
    _reset_jwks_cache()


@pytest.mark.asyncio
async def test_fetch_jwks_raises_validation_error_when_no_cache():
    """fetch_jwks() raises UnauthorizedError when HTTP fails and no cache available."""
    _reset_jwks_cache()

    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=httpx.ConnectError("connection refused"))

    with (
        patch("app.core.auth.get_async_http_client", return_value=mock_client),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        with pytest.raises(UnauthorizedError, match="authentication service unavailable"):
            await fetch_jwks()

    _reset_jwks_cache()


# ---------------------------------------------------------------------------
# verify_token_async() — loop-based audience validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_verify_token_async_happy_path():
    """verify_token_async() decodes and returns the JWT payload on success."""
    jwks_data = {
        "keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "test-n", "e": "AQAB"}]
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
        mock_settings.return_value = _mock_settings()

        result = await verify_token_async("some.jwt.token")

    assert result["sub"] == "auth0|user123"
    assert result["email"] == "user@example.com"


@pytest.mark.asyncio
async def test_verify_token_async_tries_user_audience_first():
    """verify_token_async() tries user_audience before service audience."""
    jwks_data = {
        "keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "test-n", "e": "AQAB"}]
    }
    expected_payload = {"sub": "auth0|user123", "permissions": [OPS_AGENT_READ]}

    call_audiences = []

    def mock_decode(token, key, algorithms, audience, issuer):
        call_audiences.append(audience)
        if audience == "https://fraud-governance-api":
            return expected_payload
        from jose.exceptions import JWTClaimsError

        raise JWTClaimsError("audience mismatch")

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=mock_decode),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        result = await verify_token_async("some.jwt.token")

    assert result["sub"] == "auth0|user123"
    # user_audience should be tried first
    assert call_audiences[0] == "https://fraud-governance-api"


@pytest.mark.asyncio
async def test_verify_token_async_falls_back_to_service_audience():
    """verify_token_async() falls back to service audience when user_audience fails."""
    jwks_data = {
        "keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "test-n", "e": "AQAB"}]
    }
    expected_payload = {"sub": "auth0|service123", "permissions": [OPS_AGENT_READ]}

    def mock_decode(token, key, algorithms, audience, issuer):
        if audience == "https://fraud-ops-analyst-agent-api":
            return expected_payload
        from jose.exceptions import JWTClaimsError

        raise JWTClaimsError("audience mismatch")

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=mock_decode),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        result = await verify_token_async("service.jwt.token")

    assert result["sub"] == "auth0|service123"


@pytest.mark.asyncio
async def test_verify_token_async_rejects_when_no_audience_matches():
    """verify_token_async() rejects JWTs when no configured audience matches."""
    jwks_data = {
        "keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "test-n", "e": "AQAB"}]
    }

    from jose.exceptions import JWTClaimsError

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=JWTClaimsError("audience mismatch")),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        with pytest.raises(UnauthorizedError, match="Invalid or expired token"):
            await verify_token_async("unexpected.jwt.token")


@pytest.mark.asyncio
async def test_verify_token_async_raises_validation_error_on_expired():
    """verify_token_async() raises UnauthorizedError on ExpiredSignatureError."""
    from jose.exceptions import ExpiredSignatureError

    jwks_data = {"keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "x", "e": "y"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=ExpiredSignatureError("expired")),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        with pytest.raises(UnauthorizedError, match="Invalid or expired token"):
            await verify_token_async("expired.jwt.token")


@pytest.mark.asyncio
async def test_verify_token_async_raises_validation_error_on_jwt_error():
    """verify_token_async() raises UnauthorizedError on general JWTError."""
    jwks_data = {"keys": [{"kid": "key-abc", "kty": "RSA", "use": "sig", "n": "x", "e": "y"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "key-abc"}),
        patch("app.core.auth.jwt.decode", side_effect=JWTError("bad signature")),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        with pytest.raises(UnauthorizedError, match="Invalid or expired token"):
            await verify_token_async("bad.jwt.token")


@pytest.mark.asyncio
async def test_verify_token_async_raises_when_no_matching_key():
    """verify_token_async() raises UnauthorizedError when kid is not in JWKS."""
    jwks_data = {"keys": [{"kid": "different-kid", "kty": "RSA", "use": "sig"}]}

    with (
        patch("app.core.auth.fetch_jwks", new_callable=AsyncMock, return_value=jwks_data),
        patch("app.core.auth.jwt.get_unverified_header", return_value={"kid": "missing-kid"}),
        patch("app.core.auth.get_settings") as mock_settings,
    ):
        mock_settings.return_value = _mock_settings()

        with pytest.raises(UnauthorizedError, match="Invalid or expired token"):
            await verify_token_async("unknown.kid.token")


# ---------------------------------------------------------------------------
# get_user_roles() / get_user_permissions()
# ---------------------------------------------------------------------------


def test_get_user_roles_from_unified_audience_claim():
    """get_user_roles() extracts roles from the unified audience claim."""
    payload = {
        "sub": "auth0|user1",
        "https://fraud-governance-api/roles": [PLATFORM_ADMIN, FRAUD_ANALYST],
    }
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings()
        roles = get_user_roles(payload)

    assert PLATFORM_ADMIN in roles
    assert FRAUD_ANALYST in roles


def test_get_user_roles_falls_back_to_service_audience_claim():
    """get_user_roles() falls back to service audience claim if unified is absent."""
    payload = {
        "sub": "auth0|user1",
        "https://fraud-ops-analyst-agent-api/roles": [FRAUD_ANALYST],
    }
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings()
        roles = get_user_roles(payload)

    assert roles == [FRAUD_ANALYST]


def test_get_user_roles_falls_back_to_bare_claim():
    """get_user_roles() falls back to bare 'roles' claim if no audience claims exist."""
    payload = {"sub": "auth0|user1", "roles": [FRAUD_ANALYST]}
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings()
        roles = get_user_roles(payload)

    assert roles == [FRAUD_ANALYST]


def test_get_user_roles_returns_empty_list_when_missing():
    """get_user_roles() returns [] when no roles claims exist."""
    payload = {"sub": "auth0|user1"}
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings()
        roles = get_user_roles(payload)

    assert roles == []


def test_get_user_permissions_extracts_from_payload():
    """get_user_permissions() extracts the permissions claim."""
    payload = {"permissions": [OPS_AGENT_READ, OPS_AGENT_RUN]}
    assert get_user_permissions(payload) == [OPS_AGENT_READ, OPS_AGENT_RUN]


def test_get_user_permissions_returns_empty_when_missing():
    """get_user_permissions() returns [] when no permissions claim exists."""
    assert get_user_permissions({"sub": "x"}) == []


# ---------------------------------------------------------------------------
# get_current_user()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_current_user_skip_jwt_returns_bypass_user():
    """get_current_user() returns bypass user when skip_jwt_validation=True."""
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings(skip_jwt_validation=True)

        user = await get_current_user(credentials=None)

    assert user.user_id == "local-dev-user"
    assert user.is_platform_admin
    assert user.has_permission(OPS_AGENT_ADMIN)
    assert user.has_permission(OPS_AGENT_READ)


@pytest.mark.asyncio
async def test_get_current_user_skip_jwt_rejected_outside_local():
    """get_current_user() rejects bypass in non-local environments."""
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings(
            skip_jwt_validation=True, app_env=AppEnvironment.TEST
        )

        with pytest.raises(
            UnauthorizedError, match="JWT bypass is only allowed in local environment"
        ):
            await get_current_user(credentials=None)


@pytest.mark.asyncio
async def test_get_current_user_with_none_credentials_raises_validation_error():
    """get_current_user() raises UnauthorizedError when credentials=None and JWT required."""
    with patch("app.core.auth.get_settings") as mock_settings:
        mock_settings.return_value = _mock_settings(skip_jwt_validation=False)

        with pytest.raises(UnauthorizedError, match="Missing authorization header"):
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
        "https://fraud-governance-api/roles": [FRAUD_ANALYST],
    }

    with (
        patch("app.core.auth.get_settings") as mock_settings,
        patch("app.core.auth.verify_token_async", new_callable=AsyncMock) as mock_verify,
    ):
        mock_settings.return_value = _mock_settings(skip_jwt_validation=False)
        mock_verify.return_value = decoded_payload

        user = await get_current_user(credentials=mock_credentials)

    assert user.user_id == "auth0|abc123"
    assert user.email == "analyst@example.com"
    assert user.name == "Fraud Analyst"
    assert user.has_permission(OPS_AGENT_READ)
    assert user.has_permission(OPS_AGENT_RUN)
    assert not user.has_permission(OPS_AGENT_ADMIN)
    assert user.has_role(FRAUD_ANALYST)
    assert user.is_fraud_analyst


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

    with (
        patch("app.core.auth.get_settings") as mock_settings,
        pytest.raises(ForbiddenError, match="Insufficient permissions"),
    ):
        mock_settings.return_value = _mock_settings(sanitize_errors=False)
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


def test_require_scope_platform_admin_bypasses_all_scopes():
    """require_scope() bypasses check for PLATFORM_ADMIN users regardless of permissions."""
    admin_user = AuthenticatedUser(
        user_id="admin-user",
        roles=[PLATFORM_ADMIN],
        permissions=[],  # no explicit permissions
    )

    for scope in [OPS_AGENT_READ, OPS_AGENT_RUN, OPS_AGENT_ACK, OPS_AGENT_ADMIN]:
        scope_checker = require_scope(scope)
        result = scope_checker(user=admin_user)
        assert result is admin_user


def test_require_scope_admin_with_explicit_permissions_also_passes():
    """require_scope() passes for admin user who also has explicit permissions."""
    admin_user = AuthenticatedUser(
        user_id="admin-user",
        roles=[PLATFORM_ADMIN],
        permissions=[OPS_AGENT_ADMIN, OPS_AGENT_READ, OPS_AGENT_RUN],
    )

    for scope in [OPS_AGENT_READ, OPS_AGENT_RUN, OPS_AGENT_ADMIN]:
        scope_checker = require_scope(scope)
        result = scope_checker(user=admin_user)
        assert result is admin_user


def test_require_scope_forbidden_error_includes_required_scope_in_dev():
    """ForbiddenError includes details when sanitize_errors=False."""
    user = AuthenticatedUser(user_id="u1", permissions=[])
    scope_checker = require_scope(OPS_AGENT_ADMIN)

    with (
        patch("app.core.auth.get_settings") as mock_settings,
        pytest.raises(ForbiddenError) as exc_info,
    ):
        mock_settings.return_value = _mock_settings(sanitize_errors=False)
        scope_checker(user=user)

    error = exc_info.value
    assert error.details is not None
    assert error.details.get("required_scope") == OPS_AGENT_ADMIN


def test_require_scope_forbidden_error_sanitized_in_production():
    """ForbiddenError omits details when sanitize_errors=True."""
    user = AuthenticatedUser(user_id="u1", permissions=[])
    scope_checker = require_scope(OPS_AGENT_ADMIN)

    with (
        patch("app.core.auth.get_settings") as mock_settings,
        pytest.raises(ForbiddenError) as exc_info,
    ):
        mock_settings.return_value = _mock_settings(sanitize_errors=True)
        scope_checker(user=user)

    error = exc_info.value
    # Details should not be present (sanitized)
    assert error.details is None or error.details == {}
