"""Embedding client for vector similarity.

This client is intentionally small and self-contained so it can be mocked in unit tests.
"""

from __future__ import annotations

from dataclasses import dataclass

import httpx

from app.core.config import Settings, get_settings
from app.core.tracing import get_tracing_headers


@dataclass(frozen=True)
class EmbeddingResponse:
    embedding: list[float]
    model: str


class EmbeddingClient:
    """Client for generating embeddings via an Ollama-compatible endpoint."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def embed(self, text: str) -> EmbeddingResponse:
        config = self._settings.vector_search
        if not config.api_base:
            raise ValueError("VECTOR_API_BASE is required when VECTOR_ENABLED=true")

        base_url = config.api_base.rstrip("/")
        url = f"{base_url}/embed"

        timeout = httpx.Timeout(config.request_timeout_s)
        headers: dict[str, str] = {}

        # Add distributed tracing headers
        headers.update(get_tracing_headers())

        if config.api_key and config.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"

        async with httpx.AsyncClient(timeout=timeout) as client:
            response = await client.post(
                url,
                json={
                    "model": config.model_name,
                    "input": text,
                },
                headers=headers,
            )
            response.raise_for_status()
            payload = response.json()

        embeddings = payload.get("embeddings")
        if not isinstance(embeddings, list) or not embeddings:
            raise ValueError("Embedding provider returned invalid embedding payload")
        embedding = embeddings[0]
        if not isinstance(embedding, list) or not embedding:
            raise ValueError("Embedding provider returned invalid embedding payload")

        return EmbeddingResponse(embedding=[float(v) for v in embedding], model=config.model_name)
