"""Auth0 JWT token verification and authentication utilities.

Aligned with the transaction-management auth pattern:
- AuthenticatedUser model with roles + permissions
- PLATFORM_ADMIN bypass in permission checks
- Loop-based audience validation in JWT decode
- Role extraction from namespaced JWT claims
"""

import asyncio
import logging
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import AppEnvironment, get_settings
from app.core.errors import ForbiddenError, UnauthorizedError

logger = logging.getLogger(__name__)

INVALID_OR_EXPIRED_TOKEN_MSG = "Invalid or expired token"

# =============================================================================
# Role Constants (platform-wide roles — see auth-model.md)
# =============================================================================

PLATFORM_ADMIN = "PLATFORM_ADMIN"
FRAUD_ANALYST = "FRAUD_ANALYST"
FRAUD_SUPERVISOR = "FRAUD_SUPERVISOR"

# =============================================================================
# Permission/Scope Constants (this project's scopes)
# =============================================================================

OPS_AGENT_READ = "ops_agent:read"
OPS_AGENT_RUN = "ops_agent:run"
OPS_AGENT_ACK = "ops_agent:ack"
OPS_AGENT_DRAFT = "ops_agent:draft"
OPS_AGENT_ADMIN = "ops_agent:admin"

# =============================================================================
# HTTP Client & JWKS Cache
# =============================================================================

_http_client: httpx.AsyncClient | None = None
_jwks_cache: dict[str, Any] | None = None
_cache_time: datetime | None = None
_cache_lock = asyncio.Lock()

security = HTTPBearer(auto_error=True)
_optional_security = HTTPBearer(auto_error=False)


# =============================================================================
# Models
# =============================================================================


class TokenPayload(BaseModel):
    """JWT token payload."""

    sub: str
    email: str | None = None
    name: str | None = None
    permissions: list[str] = []
    exp: int


class AuthenticatedUser(BaseModel):
    """Authenticated user information."""

    user_id: str
    email: str | None = None
    name: str | None = None
    roles: list[str] = []
    permissions: list[str] = []

    @property
    def is_platform_admin(self) -> bool:
        """Check if user has platform admin role."""
        return PLATFORM_ADMIN in self.roles

    @property
    def is_fraud_analyst(self) -> bool:
        """Check if user has fraud analyst role."""
        return FRAUD_ANALYST in self.roles or self.is_platform_admin

    @property
    def is_fraud_supervisor(self) -> bool:
        """Check if user has fraud supervisor role."""
        return FRAUD_SUPERVISOR in self.roles or self.is_platform_admin

    def has_permission(self, permission: str) -> bool:
        """Check if user has a specific permission."""
        return permission in self.permissions or self.is_platform_admin

    def has_role(self, role: str) -> bool:
        """Check if user has a specific role."""
        return role in self.roles


# =============================================================================
# Audience Resolution
# =============================================================================


def _resolve_audience_candidates() -> list[str]:
    """Return configured audiences in precedence order (user_audience first)."""
    settings = get_settings()
    auth0 = settings.auth0

    accepted = getattr(auth0, "accepted_audiences", None)
    if isinstance(accepted, (tuple, list)):
        resolved = [str(a).strip() for a in accepted if isinstance(a, str) and a.strip()]
        if resolved:
            return resolved

    resolved: list[str] = []
    for value in (
        getattr(auth0, "user_audience", ""),
        getattr(auth0, "audience", ""),
    ):
        if isinstance(value, str):
            trimmed = value.strip()
            if trimmed and trimmed not in resolved:
                resolved.append(trimmed)
    return resolved


# =============================================================================
# Role & Permission Extraction
# =============================================================================


def get_user_roles(payload: dict[str, Any]) -> list[str]:
    """Extract user roles from the JWT payload.

    Roles are stored in a namespaced claim: ``{audience}/roles``.
    Tries each configured audience in precedence order.
    """
    candidates = _resolve_audience_candidates()

    for audience in candidates:
        roles_claim = f"{audience}/roles"
        roles = payload.get(roles_claim)
        if roles is None:
            continue
        if isinstance(roles, list):
            return roles
        logger.warning(f"Roles claim is not a list: {type(roles)}")
        return []

    # Fallback: bare "roles" claim
    roles = payload.get("roles", [])
    if not isinstance(roles, list):
        if roles:
            logger.warning(f"Roles claim is not a list: {type(roles)}")
        return []
    return roles


def get_user_permissions(payload: dict[str, Any]) -> list[str]:
    """Extract permissions from JWT payload.

    Auth0 adds permissions to human user tokens when RBAC is enabled.
    M2M tokens get permissions injected by the onExecuteCredentialsExchange
    Action (deployed by card-fraud-rule-management bootstrap).
    Both token types use the top-level 'permissions' array claim.
    """
    permissions = payload.get("permissions", [])
    if not isinstance(permissions, list):
        logger.warning(f"Permissions claim is not a list: {type(permissions)}")
        return []
    return permissions


# =============================================================================
# HTTP Client Management
# =============================================================================


async def get_async_http_client() -> httpx.AsyncClient:
    global _http_client
    if _http_client is None or _http_client.is_closed:
        _http_client = httpx.AsyncClient(timeout=httpx.Timeout(10.0))
    return _http_client


async def close_async_http_client() -> None:
    """Close the global async HTTP client."""
    global _http_client
    if _http_client is not None:
        try:
            if not _http_client.is_closed:
                await _http_client.aclose()
        except (RuntimeError, httpx.HTTPError) as e:
            logger.warning("Error closing HTTP client", exc_info=True, extra={"error": str(e)})
        finally:
            _http_client = None


# =============================================================================
# JWKS Cache
# =============================================================================


async def fetch_jwks() -> dict[str, Any]:
    """Fetch JWKS from Auth0."""
    global _jwks_cache, _cache_time

    settings = get_settings()
    now = datetime.now(UTC)

    async with _cache_lock:
        if _jwks_cache is not None and _cache_time is not None:
            if (now - _cache_time).total_seconds() < settings.auth0.jwks_cache_ttl:
                return _jwks_cache

        jwks_url = settings.auth0.jwks_url
        client = await get_async_http_client()

        try:
            response = await client.get(jwks_url)
            response.raise_for_status()
            _jwks_cache = response.json()
            _cache_time = now
            return _jwks_cache
        except (httpx.HTTPError, httpx.TimeoutException, ConnectionError) as e:
            logger.error("Failed to fetch JWKS", exc_info=True, extra={"error": str(e)})
            if _jwks_cache is not None:
                logger.warning("Using stale JWKS cache")
                return _jwks_cache
            raise UnauthorizedError(
                "Unable to verify token: authentication service unavailable"
            ) from e


# =============================================================================
# Token Verification
# =============================================================================


def _find_rsa_key(jwks: dict[str, Any], token: str) -> dict[str, Any]:
    """Extract RSA key from JWKS using token's key ID."""
    try:
        unverified_header = jwt.get_unverified_header(token)
    except JWTError as e:
        logger.warning(f"Invalid JWT header: {e}")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG) from None

    for key in jwks.get("keys", []):
        if key["kid"] == unverified_header["kid"]:
            return {
                "kty": key["kty"],
                "kid": key["kid"],
                "use": key["use"],
                "n": key["n"],
                "e": key["e"],
            }

    logger.error(f"Unable to find matching key for kid: {unverified_header.get('kid')}")
    raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG) from None


def _verify_token_with_key(token: str, rsa_key: dict[str, Any]) -> dict[str, Any]:
    """Verify JWT token with provided RSA key.

    Loops through configured audiences until one matches, matching the
    transaction-management pattern for multi-audience support.
    """
    settings = get_settings()
    audiences = _resolve_audience_candidates()
    if not audiences and settings.auth0.audience:
        audiences = [settings.auth0.audience]
    if not audiences:
        logger.error("No Auth0 audience configured")
        raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)

    last_claims_error: Exception | None = None

    for audience in audiences:
        try:
            payload = jwt.decode(
                token,
                rsa_key,
                algorithms=settings.auth0.algorithms_list,
                audience=audience,
                issuer=settings.auth0.issuer_url,
            )
            logger.debug(f"Token verified successfully for subject: {payload.get('sub')}")
            return payload

        except jwt.ExpiredSignatureError:
            logger.warning("Token has expired")
            raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG) from None

        except jwt.JWTClaimsError as e:
            last_claims_error = e
            continue

        except JWTError as e:
            logger.warning(f"JWT verification failed: {e}")
            raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG) from e

    if last_claims_error is not None:
        logger.warning(f"Invalid token claims: {last_claims_error}")
    raise UnauthorizedError(INVALID_OR_EXPIRED_TOKEN_MSG)


async def verify_token_async(token: str) -> dict[str, Any]:
    """Verify JWT token asynchronously."""
    jwks = await fetch_jwks()
    rsa_key = _find_rsa_key(jwks, token)
    return _verify_token_with_key(token, rsa_key)


# =============================================================================
# User Construction
# =============================================================================


def _create_bypass_user() -> AuthenticatedUser:
    """Create mock user for local development."""
    return AuthenticatedUser(
        user_id="local-dev-user",
        email="local-dev@example.com",
        name="Local Development User",
        roles=[PLATFORM_ADMIN],
        permissions=[
            OPS_AGENT_READ,
            OPS_AGENT_RUN,
            OPS_AGENT_ACK,
            OPS_AGENT_DRAFT,
            OPS_AGENT_ADMIN,
        ],
    )


async def get_current_user(
    credentials: HTTPAuthorizationCredentials | None = Depends(_optional_security),
) -> AuthenticatedUser:
    """Extract and verify JWT token, returning AuthenticatedUser object.

    When JWT validation is bypassed (via SECURITY_SKIP_JWT_VALIDATION=true),
    returns a mock user with PLATFORM_ADMIN role.

    The returned object provides:
    - user_id, email, name fields
    - roles and permissions lists
    - Helper properties: is_platform_admin, is_fraud_analyst, is_fraud_supervisor
    - Helper methods: has_permission(), has_role()
    """
    settings = get_settings()

    if settings.security.skip_jwt_validation:
        if settings.app.env != AppEnvironment.LOCAL:
            logger.error(
                "Refusing JWT bypass outside local environment",
                extra={"app_env": settings.app.env.value},
            )
            raise UnauthorizedError("JWT bypass is only allowed in local environment")
        logger.info("JWT validation bypassed - returning mock user")
        return _create_bypass_user()

    if credentials is None:
        raise UnauthorizedError("Missing authorization header")

    token = credentials.credentials
    payload = await verify_token_async(token)

    return AuthenticatedUser(
        user_id=payload.get("sub", ""),
        email=payload.get("email"),
        name=payload.get("name"),
        roles=get_user_roles(payload),
        permissions=get_user_permissions(payload),
    )


# =============================================================================
# Authorization Dependencies
# =============================================================================


def _raise_forbidden(details: dict[str, Any]) -> None:
    """Raise ForbiddenError with optional detail sanitization."""
    settings = get_settings()
    if settings.security.sanitize_errors:
        raise ForbiddenError("Insufficient permissions")
    raise ForbiddenError("Insufficient permissions", details=details)


def require_scope(required_scope: str):
    """Dependency factory that enforces a specific scope.

    Usage:
        @router.get("/investigations")
        async def list_investigations(
            user: AuthenticatedUser = Depends(require_scope("ops_agent:read"))
        ):
            ...
    """

    def scope_checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        # Platform admin has all permissions
        if user.is_platform_admin:
            logger.debug("Platform admin - scope check bypassed")
            return user

        if not user.has_permission(required_scope):
            logger.warning(
                "Access denied - user %s lacks required scope: %s. User permissions: %s",
                user.user_id,
                required_scope,
                user.permissions,
            )
            _raise_forbidden({"required_scope": required_scope})

        logger.debug("Scope check passed: user has %s", required_scope)
        return user

    return scope_checker


# =============================================================================
# Typed Annotated Dependencies
# =============================================================================

RequireOpsRead = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_READ))]
RequireOpsRun = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_RUN))]
RequireOpsAck = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_ACK))]
RequireOpsDraft = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_DRAFT))]
RequireOpsAdmin = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_ADMIN))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
