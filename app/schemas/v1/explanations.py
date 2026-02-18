"""Explanation schemas."""

from datetime import datetime

from pydantic import BaseModel


class ExplanationSection(BaseModel):
    title: str
    content: str
    priority: int


class ExplanationMetadata(BaseModel):
    model_mode: str
    llm_confidence: float | None = None


class ExplanationResponse(BaseModel):
    investigation_id: str
    transaction_id: str
    sections: list[ExplanationSection]
    markdown: str
    metadata: ExplanationMetadata
    generated_at: datetime
