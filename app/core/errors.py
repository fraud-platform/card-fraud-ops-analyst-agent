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


class ToolExecutionError(OpsAgentError):
    """A tool failed during investigation execution."""

    code = "OPS_AGENT_TOOL_EXECUTION_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str,
        tool_name: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details={**(details or {}), "tool_name": tool_name})
        self.tool_name = tool_name


class ToolPreconditionError(OpsAgentError):
    """A tool's preconditions are not met (missing required state).

    Raised when a tool cannot execute because required state fields
    (e.g. context, pattern_results) have not been populated by
    earlier pipeline stages.
    """

    code = "OPS_AGENT_TOOL_PRECONDITION_FAILED"
    status_code = 400

    def __init__(
        self,
        message: str,
        tool_name: str,
        details: dict[str, Any] | None = None,
    ):
        super().__init__(message, details={**(details or {}), "tool_name": tool_name})
        self.tool_name = tool_name


class PlannerError(OpsAgentError):
    """LLM planner failed or returned invalid response.

    Raised when the LLM planner cannot be called, times out, or returns
    an invalid tool selection. No fallback - investigation fails explicitly.
    """

    code = "OPS_AGENT_PLANNER_ERROR"
    status_code = 500

    def __init__(
        self,
        message: str,
        investigation_id: str,
        tool_name: str | None = None,
        details: dict[str, Any] | None = None,
    ):
        base_details = {"investigation_id": investigation_id}
        if tool_name:
            base_details["tool_name"] = tool_name
        super().__init__(message, details={**base_details, **(details or {})})


ERROR_STATUS_MAP: dict[type[OpsAgentError], int] = {
    ValidationError: 400,
    NotFoundError: 404,
    ForbiddenError: 403,
    ConflictError: 409,
    DependencyError: 502,
    InternalError: 500,
    ToolExecutionError: 500,
    ToolPreconditionError: 400,
    PlannerError: 500,
}


def get_status_code(error: OpsAgentError) -> int:
    """Get HTTP status code for error."""
    return ERROR_STATUS_MAP.get(type(error), 500)
