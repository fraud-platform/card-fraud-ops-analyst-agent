"""Investigation schemas."""

from datetime import datetime
from typing import Any
from uuid import UUID

from pydantic import BaseModel, Field, field_validator

from app.schemas.v1.common import (
    RecommendationStatus,
    RecommendationType,
    RunMode,
    RunStatus,
    Severity,
)


class RunRequest(BaseModel):
    mode: RunMode = RunMode.QUICK
    transaction_id: str = Field(..., min_length=1, description="Transaction UUID")
    case_id: str | None = None
    include_rule_draft_preview: bool = False

    # SECURITY: Validate UUID format to prevent injection/processing errors
    @field_validator("transaction_id")
    @classmethod
    def validate_transaction_id(cls, v: str) -> str:
        """Validate transaction_id is a valid UUID format."""
        try:
            UUID(v)
        except ValueError as err:
            raise ValueError("transaction_id must be a valid UUID") from err
        return v


class InsightSummary(BaseModel):
    insight_id: str
    severity: Severity
    summary: str
    generated_at: datetime


class RecommendationPayload(BaseModel):
    title: str
    impact: str
    model_mode: str | None = None
    llm_status: str | None = None
    llm_narrative: str | None = None
    llm_confidence: float | None = None
    llm_risk_assessment: str | None = None
    llm_error: str | None = None
    llm_model: str | None = None
    llm_latency_ms: float | None = None
    llm_reasoning_hash: str | None = None


class RecommendationDetail(BaseModel):
    recommendation_id: str
    type: RecommendationType
    status: RecommendationStatus
    priority: int = 0
    payload: RecommendationPayload


class ActionPlanItem(BaseModel):
    priority: int = 3
    action: str
    rationale: str
    evidence_ref: str | None = None
    owner: str = "fraud_analyst"


class AgenticTraceStage(BaseModel):
    enabled: bool
    status: str
    duration_ms: float | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgenticTrace(BaseModel):
    run_id: str
    model_mode: str = "deterministic"
    llm_status: str | None = None
    llm_model: str | None = None
    llm_error: str | None = None
    llm_latency_ms: float | None = None
    llm_reasoning_hash: str | None = None
    stage_durations: dict[str, float] = Field(default_factory=dict)
    stages: dict[str, AgenticTraceStage] = Field(default_factory=dict)
    feature_flags: dict[str, bool] = Field(default_factory=dict)
    safeguards: dict[str, bool] = Field(default_factory=dict)


class RunResponse(BaseModel):
    run_id: str
    status: RunStatus
    mode: RunMode
    transaction_id: str
    model_mode: str = "deterministic"
    llm_status: str | None = None
    llm_error: str | None = None
    llm_model: str | None = None
    duration_ms: float | None = None
    runtime_feature_flags: dict[str, bool] = Field(default_factory=dict)
    runtime_safeguards: dict[str, bool] = Field(default_factory=dict)
    agentic_trace: AgenticTrace | None = None
    action_plan: list[ActionPlanItem] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    insight: InsightSummary | None = None
    recommendations: list[RecommendationDetail] = Field(default_factory=list)


class DetailResponse(BaseModel):
    run_id: str
    status: RunStatus
    mode: RunMode
    transaction_id: str
    case_id: str | None = None
    started_at: datetime
    completed_at: datetime | None = None
    error_summary: str | None = None
    model_mode: str = "deterministic"
    llm_status: str | None = None
    llm_error: str | None = None
    llm_model: str | None = None
    duration_ms: float | None = None
    stage_durations: dict[str, float] = Field(default_factory=dict)
    runtime_feature_flags: dict[str, bool] = Field(default_factory=dict)
    runtime_safeguards: dict[str, bool] = Field(default_factory=dict)
    agentic_trace: AgenticTrace | None = None
    action_plan: list[ActionPlanItem] = Field(default_factory=list)
    evidence_gaps: list[str] = Field(default_factory=list)
    insight: InsightSummary | None = None
    evidence: list[dict] = Field(default_factory=list)
    recommendations: list[RecommendationDetail] = Field(default_factory=list)
