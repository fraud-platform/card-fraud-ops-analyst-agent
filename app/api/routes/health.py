"""Health check routes."""

import logging
import time

import httpx
from fastapi import APIRouter, Request
from sqlalchemy import text

from app.core.config import AppEnvironment, get_settings
from app.core.database import get_engine
from app.core.metrics import ops_agent_db_query_failures_total, ops_agent_db_query_latency_seconds
from app.core.tracing import get_tracing_headers
from app.schemas.v1.health import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse)
async def readiness_check(request: Request):
    """Readiness check with dependency status."""
    settings = get_settings()
    database_ok = False
    tm_api_ok = False
    embedding_ok: bool | None = None

    try:
        engine = get_engine()
        started = time.perf_counter()
        async with engine.connect() as conn:
            await conn.execute(text("SELECT 1"))
        ops_agent_db_query_latency_seconds.labels(query_name="health_ready_db_check").observe(
            time.perf_counter() - started
        )
        database_ok = True
    except Exception as exc:
        ops_agent_db_query_failures_total.labels(query_name="health_ready_db_check").inc()
        logger.exception(
            "Health readiness DB check failed",
            extra={"route": "/api/v1/health/ready", "dependency": "database", "error": str(exc)},
        )

    tm_client = getattr(request.app.state, "tm_client", None)
    if tm_client is not None:
        try:
            tm_api_ok = await tm_client.health_check()
        except Exception:
            logger.exception("Health readiness TM API check failed")
    else:
        logger.warning("TMClient not available on app.state for readiness check")

    if settings.vector_search.enabled:
        embedding_ok = await _check_embedding_service(settings)

    status = "ready" if (database_ok and tm_api_ok) else "degraded"

    dependencies: dict[str, bool] = {
        "database": database_ok,
        "tm_api": tm_api_ok,
    }

    if embedding_ok is not None:
        dependencies["embedding_service"] = embedding_ok

    features: dict[str, bool] = {}
    if settings.security.expose_ready_features and settings.app.env == AppEnvironment.LOCAL:
        features = {
            "enable_llm_reasoning": settings.features.enable_llm_reasoning,
            "vector_enabled": settings.vector_search.enabled,
            "enable_rule_draft_export": settings.features.enable_rule_draft_export,
        }
    return ReadyResponse(
        status=status,
        database=database_ok,
        dependencies=dependencies,
        features=features,
        embedding_service=embedding_ok,
    )


async def _check_embedding_service(settings) -> bool | None:
    """Check embedding service health when vector search is enabled.

    Returns True if healthy, False if unhealthy, None if check was not performed.
    """
    config = settings.vector_search
    if not config.enabled or not config.api_base:
        return None

    try:
        timeout = httpx.Timeout(8.0)
        headers: dict[str, str] = {**get_tracing_headers()}
        if config.api_key and config.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            base_url = config.api_base.rstrip("/")
            response = await client.post(
                f"{base_url}/embed",
                json={"model": config.model_name, "input": "ready-check"},
                headers=headers,
            )
            if response.status_code == 200:
                payload = response.json() if response.content else {}
                embeddings = payload.get("embeddings")
                if isinstance(embeddings, list) and embeddings:
                    first = embeddings[0]
                    if isinstance(first, list) and first:
                        return True
                embedding = payload.get("embedding")
                if isinstance(embedding, list) and embedding:
                    return True
                logger.warning(
                    "Embedding service readiness payload missing embedding vectors",
                    extra={"status_code": response.status_code},
                )
                return False

            if response.status_code < 500:
                logger.warning(
                    "Embedding service readiness failed with non-server status",
                    extra={"status_code": response.status_code},
                )
                return False

            logger.warning(
                "Embedding service health check returned error status",
                extra={"status_code": response.status_code},
            )
            return False
    except httpx.TimeoutException:
        logger.warning("Embedding service health check timed out")
        return False
    except Exception as exc:
        logger.warning(
            "Embedding service health check failed",
            extra={"error": str(exc)},
        )
        return False


@router.get("/health/live", response_model=HealthResponse)
async def liveness_check():
    """Liveness check."""
    return HealthResponse(status="alive")
