"""Unit tests for embedding client."""

import pytest

from app.clients.embedding_client import EmbeddingClient, EmbeddingResponse
from app.core.config import Settings, VectorSearchConfig
from app.core.tracing import clear_tracing_context, set_request_id, set_trace_parent


def _make_settings(enabled: bool = True, api_base: str = "https://api.openai.com/v1") -> Settings:
    """Create a settings object with vector search configured."""
    settings = Settings()
    settings.vector_search = VectorSearchConfig(
        enabled=enabled,
        api_base=api_base,
        model_name="text-embedding-3-large",
        dimension=1024,
    )
    return settings


class TestEmbeddingClient:
    def test_init_with_settings(self):
        settings = _make_settings()
        client = EmbeddingClient(settings)
        assert client._settings is settings

    @pytest.mark.asyncio
    async def test_embed_raises_when_no_api_base(self):
        settings = _make_settings(api_base="")
        client = EmbeddingClient(settings)
        with pytest.raises(ValueError, match="VECTOR_API_BASE"):
            await client.embed("test text")

    @pytest.mark.asyncio
    async def test_embed_calls_openai_embeddings_endpoint(self, monkeypatch: pytest.MonkeyPatch):
        """Verifies /embeddings path, 'input' and 'dimensions' body keys (OpenAI format)."""
        settings = _make_settings(api_base="https://api.openai.com/v1")
        client = EmbeddingClient(settings)

        captured_url = {}
        captured_body = {}

        class _FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                # OpenAI /embeddings returns {"data": [{"embedding": [...]}]}
                return {"data": [{"embedding": [0.1] * 1024}], "model": "text-embedding-3-large"}

        async def _fake_post(self, url, json, headers=None):
            captured_url["url"] = url
            captured_body["body"] = json
            return _FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

        result = await client.embed("amount=100\ncurrency=USD")
        assert captured_url["url"] == "https://api.openai.com/v1/embeddings"
        assert captured_body["body"]["model"] == "text-embedding-3-large"
        assert captured_body["body"]["input"] == "amount=100\ncurrency=USD"
        assert captured_body["body"]["dimensions"] == 1024
        assert isinstance(result, EmbeddingResponse)
        assert len(result.embedding) == 1024
        assert result.model == "text-embedding-3-large"

    @pytest.mark.asyncio
    async def test_embed_validates_embeddings_is_list(self, monkeypatch: pytest.MonkeyPatch):
        settings = _make_settings()
        client = EmbeddingClient(settings)

        class _BadResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": None}

        async def _fake_post(self, url, json, headers=None):
            return _BadResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

        with pytest.raises(ValueError, match="invalid embedding payload"):
            await client.embed("test")

    @pytest.mark.asyncio
    async def test_embed_validates_embeddings_not_empty(self, monkeypatch: pytest.MonkeyPatch):
        settings = _make_settings()
        client = EmbeddingClient(settings)

        class _EmptyResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": []}

        async def _fake_post(self, url, json, headers=None):
            return _EmptyResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

        with pytest.raises(ValueError, match="invalid embedding payload"):
            await client.embed("test")

    @pytest.mark.asyncio
    async def test_embed_validates_inner_embedding_not_empty(self, monkeypatch: pytest.MonkeyPatch):
        """Validates that the first embedding vector itself is non-empty."""
        settings = _make_settings()
        client = EmbeddingClient(settings)

        class _EmptyInnerResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": []}]}

        async def _fake_post(self, url, json, headers=None):
            return _EmptyInnerResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

        with pytest.raises(ValueError, match="invalid embedding payload"):
            await client.embed("test")

    @pytest.mark.asyncio
    async def test_embed_adds_auth_header_when_api_key_set(self, monkeypatch: pytest.MonkeyPatch):
        from pydantic import SecretStr

        settings = _make_settings()
        settings.vector_search.api_key = SecretStr("test-key-123")
        client = EmbeddingClient(settings)

        captured_headers = {}

        class _FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [0.5] * 1024}]}

        async def _fake_post(self, url, json, headers=None):
            captured_headers["headers"] = headers
            return _FakeResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
        await client.embed("test")
        assert "Authorization" in captured_headers["headers"]
        assert "Bearer test-key-123" in captured_headers["headers"]["Authorization"]

    @pytest.mark.asyncio
    async def test_embed_propagates_tracing_headers(self, monkeypatch: pytest.MonkeyPatch):
        settings = _make_settings()
        client = EmbeddingClient(settings)

        captured_headers = {}

        class _FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [0.5] * 1024}]}

        async def _fake_post(self, url, json, headers=None):
            captured_headers["headers"] = headers
            return _FakeResponse()

        clear_tracing_context()
        set_request_id("req-embed-123")
        set_trace_parent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
        await client.embed("test")

        assert captured_headers["headers"]["X-Request-ID"] == "req-embed-123"
        assert (
            captured_headers["headers"]["traceparent"]
            == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
        )
        clear_tracing_context()

    @pytest.mark.asyncio
    async def test_embed_converts_floats(self, monkeypatch: pytest.MonkeyPatch):
        settings = _make_settings()
        client = EmbeddingClient(settings)

        class _IntResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [1, 2, 3]}]}

        async def _fake_post(self, url, json, headers=None):
            return _IntResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
        result = await client.embed("test")
        assert all(isinstance(v, float) for v in result.embedding)

    @pytest.mark.asyncio
    async def test_embed_extracts_first_embedding_from_batch(self, monkeypatch: pytest.MonkeyPatch):
        """Verifies we take embeddings[0] even when multiple are returned."""
        settings = _make_settings()
        client = EmbeddingClient(settings)

        class _BatchResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {"data": [{"embedding": [0.1, 0.2, 0.3]}, {"embedding": [0.4, 0.5, 0.6]}]}

        async def _fake_post(self, url, json, headers=None):
            return _BatchResponse()

        monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
        result = await client.embed("test")
        assert result.embedding == [0.1, 0.2, 0.3]


class TestEmbeddingResponse:
    def test_frozen_dataclass(self):
        resp = EmbeddingResponse(embedding=[0.1, 0.2], model="test-model")
        with pytest.raises(Exception):  # frozen=True raises FrozenInstanceError
            resp.model = "other"  # type: ignore[misc]
