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

        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
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

        embedding: list[float] | None = None
        embeddings = payload.get("embeddings")
        if isinstance(embeddings, list) and embeddings:
            first = embeddings[0]
            if isinstance(first, list) and first:
                embedding = [float(v) for v in first]

        if embedding is None:
            single = payload.get("embedding")
            if isinstance(single, list) and single:
                embedding = [float(v) for v in single]

        if embedding is None:
            raise ValueError("Embedding provider returned invalid embedding payload")

        model_name = str(payload.get("model") or config.model_name)
        return EmbeddingResponse(embedding=embedding, model=model_name)
