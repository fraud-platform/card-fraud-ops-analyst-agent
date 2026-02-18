"""Health check routes."""

import logging
import time

from fastapi import APIRouter
from sqlalchemy import text

from app.core.config import AppEnvironment, get_settings
from app.core.database import get_engine
from app.core.metrics import ops_agent_db_query_failures_total, ops_agent_db_query_latency_seconds
from app.schemas.v1.health import HealthResponse, ReadyResponse

router = APIRouter(tags=["health"])
logger = logging.getLogger(__name__)


@router.get("/health", response_model=HealthResponse)
async def health_check():
    """Basic health check."""
    return HealthResponse(status="ok")


@router.get("/health/ready", response_model=ReadyResponse)
async def readiness_check():
    """Readiness check with dependency status."""
    settings = get_settings()
    database_ok = False
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
        database_ok = False

    status = "ready" if database_ok else "degraded"
    features: dict[str, bool] = {}
    # Feature flags are operationally sensitive; keep hidden unless explicitly
    # enabled for local debugging.
    if settings.security.expose_ready_features and settings.app.env == AppEnvironment.LOCAL:
        features = {
            "enable_llm_reasoning": settings.features.enable_llm_reasoning,
            "vector_enabled": settings.vector_search.enabled,
            "counter_evidence_enabled": settings.features.counter_evidence_enabled,
            "conflict_matrix_enabled": settings.features.conflict_matrix_enabled,
            "explanation_builder_enabled": settings.features.explanation_builder_enabled,
            "enable_rule_draft_export": settings.features.enable_rule_draft_export,
        }
    return ReadyResponse(
        status=status,
        database=database_ok,
        dependencies={"database": database_ok},
        features=features,
    )


@router.get("/health/live", response_model=HealthResponse)
async def liveness_check():
    """Liveness check."""
    return HealthResponse(status="alive")
