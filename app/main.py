"""Card Fraud Ops Analyst Agent Service.

This service provides APIs for autonomous fraud investigation,
insights, and recommendations for human analysts.
"""

import uuid
from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from opentelemetry import trace
from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
from opentelemetry.instrumentation.fastapi import FastAPIInstrumentor
from opentelemetry.sdk.resources import SERVICE_NAME, Resource
from opentelemetry.sdk.trace import TracerProvider
from opentelemetry.sdk.trace.export import BatchSpanProcessor

from app.api.routes.health import router as health_router
from app.api.routes.insights import router as insights_router
from app.api.routes.investigations import router as investigations_router
from app.api.routes.monitoring import router as monitoring_router
from app.api.routes.recommendations import router as recommendations_router
from app.core.auth import close_async_http_client
from app.core.config import AppEnvironment, Settings, get_settings
from app.core.database import get_engine, get_session_factory, reset_engine
from app.core.errors import OpsAgentError, get_status_code
from app.core.logging import setup_logging
from app.core.tracing import clear_tracing_context, set_request_id, set_trace_parent

logger = structlog.get_logger(__name__)

API_V1_PREFIX = "/api/v1"
OPS_AGENT_PREFIX = "/ops-agent"
API_CSP_POLICY = (
    "default-src 'none'; frame-ancestors 'none'; base-uri 'none'; "
    "form-action 'none'; object-src 'none'"
)
DOCS_CSP_POLICY = (
    "default-src 'self'; img-src 'self' data:; style-src 'self' 'unsafe-inline'; "
    "script-src 'self' 'unsafe-inline'; frame-ancestors 'none'; object-src 'none'; "
    "base-uri 'self'"
)


def _request_log_context(request: Request) -> dict[str, str]:
    return {
        "path": request.url.path,
        "method": request.method,
        "query": request.url.query,
        "request_id": request.headers.get("x-request-id", ""),
        "client_host": request.client.host if request.client else "",
    }


def _is_docs_path(path: str) -> bool:
    return path.startswith("/docs") or path.startswith("/redoc") or path.startswith("/openapi.json")


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncGenerator[None]:
    """Application lifespan context manager."""
    settings = get_settings()
    setup_logging()

    logger.info(
        "Starting Card Fraud Ops Analyst Agent",
        app=settings.app.name,
        env=settings.app.env.value,
        version=settings.app.version,
    )

    engine = get_engine()
    session_factory = get_session_factory()

    app.state.settings = settings
    app.state.engine = engine
    app.state.session_factory = session_factory

    # Initialize TMClient for readiness checks and service injection
    from app.clients.tm_client import TMClient

    tm_client = TMClient(config=settings.tm_client)
    app.state.tm_client = tm_client

    yield

    await tm_client.close()
    await close_async_http_client()
    await reset_engine()

    logger.info("Card Fraud Ops Analyst Agent stopped")


def create_app() -> FastAPI:
    """Create and configure the FastAPI application."""
    settings = get_settings()

    app = FastAPI(
        title="Card Fraud Ops Analyst Agent",
        description=(
            "LangGraph-based autonomous fraud analyst assistant. "
            "Uses planner-driven tool orchestration for fraud investigation."
        ),
        version=settings.app.version,
        lifespan=lifespan,
        docs_url="/docs" if settings.app.env != AppEnvironment.PROD else None,
        redoc_url="/redoc" if settings.app.env != AppEnvironment.PROD else None,
        openapi_url="/openapi.json" if settings.app.env != AppEnvironment.PROD else None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.security.cors_allowed_origins,
        allow_credentials=settings.security.cors_allow_credentials,
        allow_methods=settings.security.cors_allow_methods,
        allow_headers=settings.security.cors_allow_headers,
    )

    # Monitoring routes are API-versioned and require auth.
    app.include_router(monitoring_router, prefix=API_V1_PREFIX)
    app.include_router(health_router, prefix=API_V1_PREFIX)
    app.include_router(investigations_router, prefix=API_V1_PREFIX + OPS_AGENT_PREFIX)
    app.include_router(insights_router, prefix=API_V1_PREFIX + OPS_AGENT_PREFIX)
    app.include_router(recommendations_router, prefix=API_V1_PREFIX + OPS_AGENT_PREFIX)

    setup_telemetry(app, settings)

    @app.middleware("http")
    async def request_id_middleware(request: Request, call_next):
        """Extract and propagate request ID for distributed tracing.

        1. Extract X-Request-ID from incoming request (or generate UUID)
        2. Extract traceparent header for W3C trace context propagation
        3. Store in contextvars for outbound HTTP clients
        4. Return X-Request-ID in response header

        This enables request correlation across services:
        - Portal -> Ops Agent -> Rule Management
        - Portal -> Ops Agent -> Ollama (LLM)
        - Portal -> Ops Agent -> Ollama (Embeddings)
        """
        # Extract or generate request ID
        incoming_rid = request.headers.get("x-request-id") or request.headers.get("X-Request-ID")
        request_id = incoming_rid or str(uuid.uuid4())

        # Store in context for outbound clients
        set_request_id(request_id)

        # Extract W3C traceparent for distributed tracing
        set_trace_parent(request.headers.get("traceparent"))

        # Add to request state for logging
        request.state.request_id = request_id

        try:
            # Process request
            response = await call_next(request)
        finally:
            # Prevent context leakage across requests in long-lived workers.
            clear_tracing_context()

        # Always return request ID in response (even if we generated it)
        response.headers["X-Request-ID"] = request_id

        return response

    @app.middleware("http")
    async def payload_size_guard(request: Request, call_next):
        # Get request ID from context (set by request_id_middleware)
        request_id = getattr(request.state, "request_id", "")

        request_context = _request_log_context(request)
        # Add request_id to all log context from this middleware
        if request_id:
            request_context["request_id"] = request_id

        max_request = settings.security.max_request_size_bytes
        max_response = settings.security.max_response_size_bytes

        content_length = request.headers.get("content-length")
        if content_length:
            try:
                if int(content_length) > max_request:
                    logger.warning(
                        "Request payload exceeds configured size limit",
                        **request_context,
                        content_length=content_length,
                        max_request_size_bytes=max_request,
                    )
                    return JSONResponse(
                        status_code=413, content={"detail": "Request payload too large"}
                    )
            except ValueError:
                logger.warning(
                    "Invalid Content-Length header",
                    **request_context,
                    content_length=content_length,
                )
        elif request.method in {"POST", "PUT", "PATCH"}:
            body = await request.body()
            if len(body) > max_request:
                logger.warning(
                    "Request payload exceeds configured size limit",
                    **request_context,
                    content_length=len(body),
                    max_request_size_bytes=max_request,
                )
                return JSONResponse(
                    status_code=413, content={"detail": "Request payload too large"}
                )

        response = await call_next(request)

        response_length = response.headers.get("content-length")
        if response_length:
            try:
                if int(response_length) > max_response:
                    logger.error(
                        "Response payload exceeds configured size limit",
                        **request_context,
                        content_length=response_length,
                        max_response_size_bytes=max_response,
                    )
                    return JSONResponse(
                        status_code=500, content={"detail": "Response payload too large"}
                    )
            except ValueError:
                logger.warning(
                    "Invalid response Content-Length header",
                    **request_context,
                    content_length=response_length,
                )

        return response

    @app.middleware("http")
    async def security_headers_middleware(request: Request, call_next):
        """Set baseline security headers for all responses."""
        response = await call_next(request)

        csp_policy = DOCS_CSP_POLICY if _is_docs_path(request.url.path) else API_CSP_POLICY
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault(
            "Strict-Transport-Security", "max-age=63072000; includeSubDomains; preload"
        )
        response.headers.setdefault("Content-Security-Policy", csp_policy)
        return response

    @app.exception_handler(OpsAgentError)
    async def domain_error_handler(request: Request, exc: OpsAgentError) -> JSONResponse:
        """Handle domain-specific errors."""
        status_code = get_status_code(exc)
        logger.warning(
            "Domain exception",
            **_request_log_context(request),
            status_code=status_code,
            error=exc.message,
            error_details=exc.details or {},
        )
        return JSONResponse(
            status_code=status_code,
            content={
                "detail": exc.message,
                **({"errors": exc.details} if exc.details else {}),
            },
        )

    @app.exception_handler(Exception)
    async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
        """Handle unexpected exceptions."""
        logger.exception(
            "Unhandled exception",
            **_request_log_context(request),
            error=str(exc),
        )
        return JSONResponse(
            status_code=500,
            content={"detail": "Internal server error"},
        )

    return app


def setup_telemetry(app: FastAPI, settings: Settings) -> None:
    """Setup OpenTelemetry instrumentation."""
    if not settings.observability.otlp_endpoint:
        return

    resource = Resource(
        attributes={
            SERVICE_NAME: settings.observability.service_name,
        }
    )

    provider = TracerProvider(resource=resource)
    exporter = OTLPSpanExporter(
        endpoint=settings.observability.otlp_endpoint,
        insecure=settings.observability.otlp_insecure,
    )
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)

    FastAPIInstrumentor.instrument_app(app)


def run() -> None:
    """Run the application using uvicorn."""
    import uvicorn

    settings = get_settings()

    uvicorn.run(
        "app.main:create_app",
        host=settings.server.host,
        port=settings.server.port,
        reload=settings.app.env == AppEnvironment.LOCAL,
        workers=1 if settings.app.env == AppEnvironment.LOCAL else settings.server.workers,
        log_level=settings.app.log_level.lower(),
    )


if __name__ == "__main__":
    run()
