"""Base tool interface for investigation tools."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.agent.state import InvestigationState


class BaseTool(ABC):
    """Abstract base class for all investigation tools.

    Contract:
    - MUST NOT mutate the input state dict
    - MUST return a new dict with updated fields
    - MUST be deterministic (same input -> same output)
    - MUST be idempotent (re-running produces same result)
    - MUST NOT call other tools
    - MUST NOT perform planning decisions
    - MUST NOT directly persist to database
    - SHOULD complete within tool_timeout_seconds (30s default)
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique tool identifier used in registry and planner."""
        ...

    @property
    @abstractmethod
    def description(self) -> str:
        """Human-readable description included in planner prompt."""
        ...

    @abstractmethod
    async def execute(self, state: InvestigationState) -> InvestigationState:
        """Execute tool logic and return updated state."""
        ...
