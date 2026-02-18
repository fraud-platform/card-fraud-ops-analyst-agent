"""Unit tests for dependencies module."""

from app.core.dependencies import (
    AuthenticatedUser,
)


def test_authenticated_user_defaults():
    user = AuthenticatedUser(user_id="test")
    assert user.user_id == "test"
    assert user.email is None
    assert user.name is None
    assert user.permissions == []


def test_authenticated_user_permissions():
    user = AuthenticatedUser(
        user_id="test",
        permissions=["ops_agent:read", "ops_agent:run"],
    )
    assert user.has_permission("ops_agent:read") is True
    assert user.has_permission("ops_agent:write") is False
