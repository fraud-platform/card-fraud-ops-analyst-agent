"""Investigation schemas for agentic API."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator


class RunRequest(BaseModel):
    transaction_id: str = Field(..., min_length=1, description="Transaction UUID")
    mode: str = "FULL"

    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, v: str) -> str:
        try:
            UUID(v)
        except ValueError as err:
            raise ValueError("transaction_id must be a valid UUID") from err
        return v


class InvestigationSummary(BaseModel):
    investigation_id: str
    transaction_id: str
    status: str
    severity: str
    started_at: datetime | None = None
    completed_at: datetime | None = None


class InvestigationListResponse(BaseModel):
    investigations: list[InvestigationSummary]
    total: int = 0


class PlannerDecisionSchema(BaseModel):
    step: int
    selected_tool: str
    reason: str
    confidence: float = Field(ge=0.0, le=1.0)
    timestamp: str


class ToolExecutionSchema(BaseModel):
    tool_name: str
    input_summary: dict[str, Any] = Field(default_factory=dict)
    output_summary: dict[str, Any] = Field(default_factory=dict)
    execution_time_ms: int
    status: str
    error_message: str | None = None
    timestamp: str


class RecommendationSchema(BaseModel):
    type: str
    priority: int = 0
    title: str
    impact: str
    signature_hash: str | None = None


class InvestigationResponse(BaseModel):
    investigation_id: str
    transaction_id: str
    status: str
    severity: str
    confidence_score: float = Field(ge=0.0, le=1.0)
    step_count: int
    max_steps: int = 20
    planner_decisions: list[PlannerDecisionSchema] = Field(default_factory=list)
    tool_executions: list[ToolExecutionSchema] = Field(default_factory=list)
    recommendations: list[RecommendationSchema] = Field(default_factory=list)
    started_at: str
    completed_at: str | None = None
    total_duration_ms: int | None = None


class InvestigationDetailResponse(InvestigationResponse):
    context: dict[str, Any] = Field(default_factory=dict)
    evidence: list[dict[str, Any]] = Field(default_factory=list)
    pattern_results: dict[str, Any] = Field(default_factory=dict)
    similarity_results: dict[str, Any] = Field(default_factory=dict)
    reasoning: dict[str, Any] = Field(default_factory=dict)
    hypotheses: list[str] = Field(default_factory=list)
    rule_draft: dict[str, Any] | None = None


class ResumeRequest(BaseModel):
    pass


class ResumeResponse(InvestigationResponse):
    resumed_from_step: int | None = None
