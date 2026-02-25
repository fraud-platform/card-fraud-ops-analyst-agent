"""Common schemas: enums and error responses."""

from enum import StrEnum
from typing import Any

from pydantic import BaseModel


class Severity(StrEnum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RunMode(StrEnum):
    QUICK = "quick"
    DEEP = "deep"


class RunStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


class InvestigationStatus(StrEnum):
    PENDING = "PENDING"
    IN_PROGRESS = "IN_PROGRESS"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class ToolStatus(StrEnum):
    SUCCESS = "SUCCESS"
    FAILED = "FAILED"
    TIMED_OUT = "TIMED_OUT"


class RecommendationStatus(StrEnum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    REJECTED = "REJECTED"
    EXPORTED = "EXPORTED"


class RecommendationType(StrEnum):
    REVIEW_PRIORITY = "review_priority"
    CASE_ACTION = "case_action"
    RULE_CANDIDATE = "rule_candidate"


class ExportStatus(StrEnum):
    NOT_EXPORTED = "NOT_EXPORTED"
    PENDING = "PENDING"
    EXPORTED = "EXPORTED"
    FAILED = "FAILED"


class ModelMode(StrEnum):
    AGENTIC = "agentic"
    # Legacy values remain for backward-compatible reads from older rows/artifacts.
    DETERMINISTIC = "deterministic"
    HYBRID = "hybrid"


class ApiError(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None


class PaginatedResponse(BaseModel):
    items: list[Any]
    next_cursor: str | None = None
    has_more: bool = False
