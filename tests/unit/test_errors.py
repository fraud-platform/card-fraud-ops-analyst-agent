"""Unit tests for errors module."""

from app.core.errors import (
    ConflictError,
    ForbiddenError,
    InternalError,
    NotFoundError,
    OpsAgentError,
    ValidationError,
    get_status_code,
)


def test_ops_agent_error_base():
    error = OpsAgentError("test message")
    assert error.message == "test message"
    assert error.code == "OPS_AGENT_INTERNAL_ERROR"
    assert error.status_code == 500


def test_validation_error():
    error = ValidationError("invalid request")
    assert error.code == "OPS_AGENT_INVALID_REQUEST"
    assert error.status_code == 400


def test_not_found_error():
    error = NotFoundError("not found")
    assert error.code == "OPS_AGENT_NOT_FOUND"
    assert error.status_code == 404


def test_forbidden_error():
    error = ForbiddenError("forbidden")
    assert error.code == "OPS_AGENT_SCOPE_FORBIDDEN"
    assert error.status_code == 403


def test_conflict_error():
    error = ConflictError("conflict")
    assert error.code == "OPS_AGENT_CONFLICT"
    assert error.status_code == 409


def test_internal_error():
    error = InternalError("internal")
    assert error.code == "OPS_AGENT_INTERNAL_ERROR"
    assert error.status_code == 500


def test_error_with_details():
    error = ValidationError("error", details={"field": "value"})
    assert error.details == {"field": "value"}


def test_get_status_code():
    assert get_status_code(ValidationError("test")) == 400
    assert get_status_code(NotFoundError("test")) == 404
    assert get_status_code(ForbiddenError("test")) == 403
    assert get_status_code(ConflictError("test")) == 409
    assert get_status_code(OpsAgentError("test")) == 500
