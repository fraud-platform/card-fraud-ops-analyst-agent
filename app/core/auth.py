"""Auth0 JWT token verification and authentication utilities."""

import asyncio
import logging
import threading
from datetime import UTC, datetime
from typing import Annotated, Any

import httpx
from fastapi import Depends
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from jose import JWTError, jwt
from pydantic import BaseModel

from app.core.config import AppEnvironment, get_settings
from app.core.errors import ForbiddenError, ValidationError

logger = logging.getLogger(__name__)

INVALID_OR_EXPIRED_TOKEN_MSG = "Invalid or expired token"

_http_client: httpx.AsyncClient | None = None
_jwks_cache: dict[str, Any] | None = None
_cache_time: datetime | None = None
_cache_lock = asyncio.Lock()
_thread_lock = threading.RLock()

security = HTTPBearer(auto_error=True)
_optional_security = HTTPBearer(auto_error=False)


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
    permissions: list[str] = []

    def has_permission(self, permission: str) -> bool:
        return permission in self.permissions


OPS_AGENT_READ = "ops_agent:read"
OPS_AGENT_RUN = "ops_agent:run"
OPS_AGENT_ACK = "ops_agent:ack"
OPS_AGENT_DRAFT = "ops_agent:draft"
OPS_AGENT_ADMIN = "ops_agent:admin"


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
            raise ValidationError(
                "Unable to verify token: authentication service unavailable"
            ) from e


async def verify_token_async(token: str) -> dict[str, Any]:
    """Verify JWT token asynchronously."""
    settings = get_settings()

    try:
        jwks = await fetch_jwks()
        unverified_header = jwt.get_unverified_header(token)

        rsa_key = None
        for key in jwks.get("keys", []):
            if key["kid"] == unverified_header["kid"]:
                rsa_key = {
                    "kty": key["kty"],
                    "kid": key["kid"],
                    "use": key["use"],
                    "n": key["n"],
                    "e": key["e"],
                }
                break

        if rsa_key is None:
            raise ValidationError(INVALID_OR_EXPIRED_TOKEN_MSG)

        payload = jwt.decode(
            token,
            rsa_key,
            algorithms=settings.auth0.algorithms_list,
            audience=settings.auth0.audience,
            issuer=settings.auth0.issuer_url,
        )
        return payload

    except jwt.ExpiredSignatureError:
        raise ValidationError(INVALID_OR_EXPIRED_TOKEN_MSG) from None
    except JWTError as e:
        logger.warning(f"JWT verification failed: {e}")
        raise ValidationError(INVALID_OR_EXPIRED_TOKEN_MSG) from e


def _create_bypass_user() -> AuthenticatedUser:
    """Create mock user for local development."""
    return AuthenticatedUser(
        user_id="local-dev-user",
        email="local-dev@example.com",
        name="Local Development User",
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
    """Extract and verify JWT token, returning AuthenticatedUser object."""
    settings = get_settings()

    if settings.security.skip_jwt_validation:
        if settings.app.env != AppEnvironment.LOCAL:
            logger.error(
                "Refusing JWT bypass outside local environment",
                extra={"app_env": settings.app.env.value},
            )
            raise ValidationError("JWT bypass is only allowed in local environment")
        logger.info("JWT validation bypassed - returning mock user")
        return _create_bypass_user()

    if credentials is None:
        raise ValidationError("Missing authorization header")

    token = credentials.credentials
    payload = await verify_token_async(token)

    return AuthenticatedUser(
        user_id=payload.get("sub", ""),
        email=payload.get("email"),
        name=payload.get("name"),
        permissions=payload.get("permissions", []),
    )


def require_scope(required_scope: str):
    """Dependency factory that enforces a specific scope."""

    def scope_checker(user: AuthenticatedUser = Depends(get_current_user)) -> AuthenticatedUser:
        if not user.has_permission(required_scope):
            logger.warning(
                f"Access denied - user {user.user_id} lacks required scope: {required_scope}",
                extra={"user_permissions": user.permissions},
            )
            raise ForbiddenError(
                "Insufficient permissions",
                details={"required_scope": required_scope},
            )
        return user

    return scope_checker


RequireOpsRead = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_READ))]
RequireOpsRun = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_RUN))]
RequireOpsAck = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_ACK))]
RequireOpsDraft = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_DRAFT))]
RequireOpsAdmin = Annotated[AuthenticatedUser, Depends(require_scope(OPS_AGENT_ADMIN))]
CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
