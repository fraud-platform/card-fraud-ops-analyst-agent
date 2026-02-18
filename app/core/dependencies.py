"""Dependency injection type aliases."""

from app.core.auth import (
    AuthenticatedUser,
    CurrentUser,
    RequireOpsAck,
    RequireOpsAdmin,
    RequireOpsDraft,
    RequireOpsRead,
    RequireOpsRun,
)

__all__ = [
    "AuthenticatedUser",
    "CurrentUser",
    "RequireOpsRead",
    "RequireOpsRun",
    "RequireOpsAck",
    "RequireOpsDraft",
    "RequireOpsAdmin",
]
