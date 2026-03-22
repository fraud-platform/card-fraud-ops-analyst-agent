"""Unit tests for auth module."""

from app.core.auth import (
    FRAUD_ANALYST,
    FRAUD_SUPERVISOR,
    OPS_AGENT_ACK,
    OPS_AGENT_ADMIN,
    OPS_AGENT_DRAFT,
    OPS_AGENT_READ,
    OPS_AGENT_RUN,
    PLATFORM_ADMIN,
    AuthenticatedUser,
    TokenPayload,
    _create_bypass_user,
    get_user_permissions,
)

# ---------------------------------------------------------------------------
# AuthenticatedUser model
# ---------------------------------------------------------------------------


def test_authenticated_user_has_permission():
    user = AuthenticatedUser(
        user_id="test-user",
        email="test@example.com",
        permissions=[OPS_AGENT_READ, OPS_AGENT_RUN],
    )
    assert user.has_permission(OPS_AGENT_READ) is True
    assert user.has_permission(OPS_AGENT_ACK) is False


def test_authenticated_user_platform_admin_bypasses_permission_check():
    """PLATFORM_ADMIN role grants all permissions even without explicit scopes."""
    user = AuthenticatedUser(
        user_id="admin-user",
        roles=[PLATFORM_ADMIN],
        permissions=[],  # no explicit permissions
    )
    assert user.has_permission(OPS_AGENT_READ) is True
    assert user.has_permission(OPS_AGENT_RUN) is True
    assert user.has_permission(OPS_AGENT_ADMIN) is True


def test_authenticated_user_is_platform_admin():
    admin = AuthenticatedUser(user_id="a", roles=[PLATFORM_ADMIN])
    non_admin = AuthenticatedUser(user_id="b", roles=[FRAUD_ANALYST])
    assert admin.is_platform_admin is True
    assert non_admin.is_platform_admin is False


def test_authenticated_user_is_fraud_analyst():
    analyst = AuthenticatedUser(user_id="a", roles=[FRAUD_ANALYST])
    admin = AuthenticatedUser(user_id="b", roles=[PLATFORM_ADMIN])
    viewer = AuthenticatedUser(user_id="c", roles=[])
    assert analyst.is_fraud_analyst is True
    assert admin.is_fraud_analyst is True  # admin implies analyst
    assert viewer.is_fraud_analyst is False


def test_authenticated_user_is_fraud_supervisor():
    supervisor = AuthenticatedUser(user_id="a", roles=[FRAUD_SUPERVISOR])
    admin = AuthenticatedUser(user_id="b", roles=[PLATFORM_ADMIN])
    analyst = AuthenticatedUser(user_id="c", roles=[FRAUD_ANALYST])
    assert supervisor.is_fraud_supervisor is True
    assert admin.is_fraud_supervisor is True  # admin implies supervisor
    assert analyst.is_fraud_supervisor is False


def test_authenticated_user_has_role():
    user = AuthenticatedUser(user_id="a", roles=[FRAUD_ANALYST, FRAUD_SUPERVISOR])
    assert user.has_role(FRAUD_ANALYST) is True
    assert user.has_role(FRAUD_SUPERVISOR) is True
    assert user.has_role(PLATFORM_ADMIN) is False


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


# ---------------------------------------------------------------------------
# Bypass user
# ---------------------------------------------------------------------------


def test_create_bypass_user():
    user = _create_bypass_user()
    assert user.user_id == "local-dev-user"
    assert user.has_permission(OPS_AGENT_ADMIN) is True
    assert user.has_permission(OPS_AGENT_READ) is True
    assert user.is_platform_admin is True
    assert PLATFORM_ADMIN in user.roles


# ---------------------------------------------------------------------------
# get_user_permissions
# ---------------------------------------------------------------------------


def test_get_user_permissions_from_permissions_claim():
    """Human user tokens have permissions in the 'permissions' array."""
    payload = {"permissions": [OPS_AGENT_READ, OPS_AGENT_RUN]}
    assert get_user_permissions(payload) == [OPS_AGENT_READ, OPS_AGENT_RUN]


def test_get_user_permissions_m2m_with_injected_permissions():
    """M2M tokens get permissions injected by onExecuteCredentialsExchange Action."""
    payload = {
        "gty": "client-credentials",
        "permissions": [OPS_AGENT_READ, OPS_AGENT_RUN],
    }
    assert get_user_permissions(payload) == [OPS_AGENT_READ, OPS_AGENT_RUN]


def test_get_user_permissions_empty():
    """No permissions returns empty list."""
    assert get_user_permissions({}) == []


def test_get_user_permissions_malformed():
    """Non-list permissions returns empty list."""
    assert get_user_permissions({"permissions": "not-a-list"}) == []


# ---------------------------------------------------------------------------
# TokenPayload model
# ---------------------------------------------------------------------------


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
