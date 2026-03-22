"""Dependency injection type aliases."""

from app.core.auth import (
    FRAUD_ANALYST,
    FRAUD_SUPERVISOR,
    PLATFORM_ADMIN,
    AuthenticatedUser,
    CurrentUser,
    RequireOpsAck,
    RequireOpsAdmin,
    RequireOpsDraft,
    RequireOpsRead,
    RequireOpsRun,
    get_current_user,
    require_scope,
)

__all__ = [
    "PLATFORM_ADMIN",
    "FRAUD_ANALYST",
    "FRAUD_SUPERVISOR",
    "AuthenticatedUser",
    "CurrentUser",
    "RequireOpsRead",
    "RequireOpsRun",
    "RequireOpsAck",
    "RequireOpsDraft",
    "RequireOpsAdmin",
    "get_current_user",
    "require_scope",
]
