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
    """OpenAI-compatible embeddings client."""

    def __init__(self, settings: Settings | None = None) -> None:
        self._settings = settings or get_settings()

    async def embed(self, text: str) -> EmbeddingResponse:
        config = self._settings.vector_search
        if not config.api_base:
            raise ValueError("VECTOR_API_BASE is required when VECTOR_ENABLED=true")

        base_url = config.api_base.rstrip("/")
        url = f"{base_url}/embeddings"
        body: dict = {
            "model": config.model_name,
            "input": text,
            "dimensions": config.dimension,
        }

        headers: dict[str, str] = {**get_tracing_headers()}
        if config.api_key and config.api_key.get_secret_value():
            headers["Authorization"] = f"Bearer {config.api_key.get_secret_value()}"

        timeout = httpx.Timeout(config.request_timeout_s)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            response = await client.post(url, json=body, headers=headers)
            response.raise_for_status()
            payload = response.json()

        # OpenAI format: {"data": [{"embedding": [...], "index": 0}]}
        data_list = payload.get("data")
        if isinstance(data_list, list) and data_list:
            first = data_list[0]
            if isinstance(first, dict):
                emb = first.get("embedding")
                if isinstance(emb, list) and emb:
                    return EmbeddingResponse(
                        embedding=[float(v) for v in emb],
                        model=str(payload.get("model") or config.model_name),
                    )

        raise ValueError("Embedding provider returned invalid embedding payload")
