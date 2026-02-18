"""Conflict matrix schemas."""

from pydantic import BaseModel


class ConflictMatrixResponse(BaseModel):
    pattern_vs_similarity: str
    fraud_vs_counter_evidence: str
    deterministic_vs_llm: str
    overall_conflict_score: float
    resolution_strategy: str
