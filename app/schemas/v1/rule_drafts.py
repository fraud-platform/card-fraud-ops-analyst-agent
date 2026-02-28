"""Rule draft schemas."""

import re
from datetime import datetime
from typing import Any

from pydantic import BaseModel, field_validator

from app.schemas.v1.common import ExportStatus


class RuleConditionSchema(BaseModel):
    """Schema for rule condition."""

    field_name: str
    operator: str
    value: Any
    logical_op: str = "AND"


class RuleDraftPayloadSchema(BaseModel):
    """Schema for rule draft payload."""

    rule_name: str
    rule_description: str
    conditions: list[RuleConditionSchema]
    thresholds: dict[str, Any]
    metadata: dict[str, Any]


class CreateRequest(BaseModel):
    recommendation_id: str
    package_version: str = "1.0"
    dry_run: bool = False


class ExportRequest(BaseModel):
    target: str = "rule-management"
    target_endpoint: str = "/api/v1/rules"

    @field_validator("target_endpoint")
    @classmethod
    def validate_endpoint(cls, v: str) -> str:
        if not re.match(r"^/api/v\d+/[\w\-/]+$", v):
            raise ValueError("Invalid target endpoint path")
        return v


class RuleDraftResponse(BaseModel):
    rule_draft_id: str
    recommendation_id: str
    package_version: str
    export_status: ExportStatus
    exported_to: str | None = None
    exported_at: datetime | None = None
    created_at: datetime
    draft_payload: dict[str, Any] | None = None
    validation_errors: list[str] | None = None
    export_error: str | None = None
