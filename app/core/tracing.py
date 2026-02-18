"""Distributed tracing context for request ID propagation.

This module provides contextvars-based storage for request-scoped tracing
information that needs to propagate across async boundaries to outbound HTTP
calls (LLM provider, Rule Management, Embedding service).
"""

import uuid
from contextvars import ContextVar
from typing import Any

# Request-scoped tracing context
request_id_ctx: ContextVar[str | None] = ContextVar("request_id", default=None)
trace_parent_ctx: ContextVar[str | None] = ContextVar("trace_parent", default=None)


def get_request_id() -> str | None:
    """Get the current request ID from context."""
    return request_id_ctx.get()


def set_request_id(value: str | None) -> None:
    """Set the request ID in context."""
    if value is None:
        # Generate a new one if not provided
        value = str(uuid.uuid4())
    request_id_ctx.set(value)


def get_trace_parent() -> str | None:
    """Get the W3C traceparent header from context."""
    return trace_parent_ctx.get()


def set_trace_parent(value: str | None) -> None:
    """Set the W3C traceparent header in context."""
    trace_parent_ctx.set(value or None)


def clear_tracing_context() -> None:
    """Clear request-scoped tracing context after request completion."""
    request_id_ctx.set(None)
    trace_parent_ctx.set(None)


def get_tracing_headers() -> dict[str, str]:
    """Get all tracing headers for outbound requests.

    Returns a dict with X-Request-ID and traceparent (if available) for
    propagation to downstream services like Rule Management, LLM providers,
    and embedding services.

    Example:
        headers = get_tracing_headers()
        async with httpx.AsyncClient() as client:
            response = await client.post(url, json=payload, headers=headers)
    """
    headers: dict[str, str] = {}

    if rid := request_id_ctx.get():
        headers["X-Request-ID"] = rid

    if tp := trace_parent_ctx.get():
        headers["traceparent"] = tp

    return headers


def bind_contextvars_to_logging() -> dict[str, Any]:
    """Get all tracing contextvars as a dict for structlog binding.

    Usage in middleware or endpoint:
        import structlog
        logger = structlog.get_logger(__name__)
        logger = logger.bind(**bind_contextvars_to_logging())
    """
    context: dict[str, Any] = {}
    if rid := request_id_ctx.get():
        context["request_id"] = rid
    if tp := trace_parent_ctx.get():
        context["trace_parent"] = tp
    return context
