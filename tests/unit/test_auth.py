"""Unit tests for auth module."""

from app.core.auth import (
    OPS_AGENT_ACK,
    OPS_AGENT_ADMIN,
    OPS_AGENT_DRAFT,
    OPS_AGENT_READ,
    OPS_AGENT_RUN,
    AuthenticatedUser,
    TokenPayload,
    _create_bypass_user,
)


def test_authenticated_user_has_permission():
    user = AuthenticatedUser(
        user_id="test-user",
        email="test@example.com",
        permissions=[OPS_AGENT_READ, OPS_AGENT_RUN],
    )
    assert user.has_permission(OPS_AGENT_READ) is True
    assert user.has_permission(OPS_AGENT_ACK) is False


def test_create_bypass_user():
    user = _create_bypass_user()
    assert user.user_id == "local-dev-user"
    assert user.has_permission(OPS_AGENT_ADMIN) is True
    assert user.has_permission(OPS_AGENT_READ) is True


def test_token_payload():
    payload = TokenPayload(
        sub="user-123",
        email="test@example.com",
        name="Test User",
        permissions=[OPS_AGENT_READ],
        exp=1234567890,
    )
    assert payload.sub == "user-123"
    assert payload.email == "test@example.com"


def test_authenticated_user_with_all_permissions():
    user = AuthenticatedUser(
        user_id="admin",
        permissions=[
            OPS_AGENT_READ,
            OPS_AGENT_RUN,
            OPS_AGENT_ACK,
            OPS_AGENT_DRAFT,
            OPS_AGENT_ADMIN,
        ],
    )
    assert user.has_permission(OPS_AGENT_READ)
    assert user.has_permission(OPS_AGENT_RUN)
    assert user.has_permission(OPS_AGENT_ACK)
    assert user.has_permission(OPS_AGENT_DRAFT)
    assert user.has_permission(OPS_AGENT_ADMIN)
