"""Unit tests for native Ollama HTTP provider."""

import pytest

from app.core.config import LLMConfig
from app.llm.provider import OllamaProvider


@pytest.mark.asyncio
async def test_ollama_provider_complete_happy_path(monkeypatch: pytest.MonkeyPatch):
    config = LLMConfig(provider="ollama/gpt-oss:120b-cloud", base_url="https://ollama.com")
    provider = OllamaProvider(config)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "model": "gpt-oss:120b-cloud",
                "message": {"role": "assistant", "content": '{"narrative":"ok"}'},
                "prompt_eval_count": 10,
                "eval_count": 5,
            }

    async def _fake_post(self, url, json):
        assert url == "https://ollama.com/api/chat"
        assert json["model"] == "gpt-oss:120b-cloud"
        assert json["stream"] is False
        return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)

    response = await provider.complete([{"role": "user", "content": "hello"}], json_mode=True)
    assert response.content == '{"narrative":"ok"}'
    assert response.model == "gpt-oss:120b-cloud"
    assert response.usage["total_tokens"] == 15
    assert response.latency_ms >= 0


@pytest.mark.asyncio
async def test_ollama_provider_strips_ollama_prefix_for_model(monkeypatch: pytest.MonkeyPatch):
    config = LLMConfig(provider="ollama/llama3.2", base_url="http://localhost:11434")
    provider = OllamaProvider(config)

    class _FakeResponse:
        def raise_for_status(self) -> None:
            return None

        def json(self):
            return {
                "model": "llama3.2",
                "message": {"role": "assistant", "content": "ok"},
                "prompt_eval_count": 1,
                "eval_count": 1,
            }

    async def _fake_post(self, url, json):
        assert url == "http://localhost:11434/api/chat"
        assert json["model"] == "llama3.2"
        return _FakeResponse()

    monkeypatch.setattr("httpx.AsyncClient.post", _fake_post)
    response = await provider.complete([{"role": "user", "content": "hello"}])
    assert response.content == "ok"
