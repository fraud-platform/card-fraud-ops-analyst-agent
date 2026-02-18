"""Health check schemas."""

from pydantic import BaseModel, Field


class HealthResponse(BaseModel):
    status: str


class ReadyResponse(BaseModel):
    status: str
    database: bool = False
    dependencies: dict[str, bool] = Field(default_factory=dict)
    features: dict[str, bool] = Field(default_factory=dict)
