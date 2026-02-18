"""Ops Agent error hierarchy."""

from typing import Any


class OpsAgentError(Exception):
    """Base exception for Ops Agent errors."""

    code = "OPS_AGENT_INTERNAL_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str,
        details: dict[str, Any] | None = None,
    ):
        self.message = message
        self.details = details
        super().__init__(message)


class ValidationError(OpsAgentError):
    """Invalid request parameters."""

    code = "OPS_AGENT_INVALID_REQUEST"
    status_code = 400


class NotFoundError(OpsAgentError):
    """Resource not found."""

    code = "OPS_AGENT_NOT_FOUND"
    status_code = 404


class ForbiddenError(OpsAgentError):
    """Access forbidden due to scope/permission."""

    code = "OPS_AGENT_SCOPE_FORBIDDEN"
    status_code = 403


class ConflictError(OpsAgentError):
    """Resource conflict (e.g., idempotency)."""

    code = "OPS_AGENT_CONFLICT"
    status_code = 409


class DependencyError(OpsAgentError):
    """External dependency failure."""

    code = "OPS_AGENT_DEPENDENCY_FAILURE"
    status_code = 502


class InternalError(OpsAgentError):
    """Internal server error."""

    code = "OPS_AGENT_INTERNAL_ERROR"
    status_code = 500


ERROR_STATUS_MAP: dict[type[OpsAgentError], int] = {
    ValidationError: 400,
    NotFoundError: 404,
    ForbiddenError: 403,
    ConflictError: 409,
    DependencyError: 502,
    InternalError: 500,
}


def get_status_code(error: OpsAgentError) -> int:
    """Get HTTP status code for error."""
    return ERROR_STATUS_MAP.get(type(error), 500)
