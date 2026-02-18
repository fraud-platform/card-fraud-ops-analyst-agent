"""Unit tests for LiteLLM provider wrapper."""

from types import SimpleNamespace

import pytest

from app.core.config import LLMConfig
from app.core.tracing import clear_tracing_context, set_request_id, set_trace_parent
from app.llm.provider import LiteLLMProvider, OllamaProvider, get_llm_provider


@pytest.mark.asyncio
async def test_litellm_provider_complete(monkeypatch: pytest.MonkeyPatch):
    config = LLMConfig(provider="anthropic/claude-sonnet-4-5-20250929")
    provider = LiteLLMProvider(config)
    captured_kwargs: dict = {}

    async def fake_acompletion(**kwargs):
        captured_kwargs.update(kwargs)
        return SimpleNamespace(
            choices=[SimpleNamespace(message=SimpleNamespace(content='{"narrative":"ok"}'))],
            model="anthropic/claude-sonnet-4-5-20250929",
            usage=SimpleNamespace(prompt_tokens=10, completion_tokens=5, total_tokens=15),
        )

    clear_tracing_context()
    set_request_id("req-llm-1")
    set_trace_parent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
    monkeypatch.setattr(provider._litellm, "acompletion", fake_acompletion)

    response = await provider.complete([{"role": "user", "content": "hello"}])

    assert response.content == '{"narrative":"ok"}'
    assert response.model == "anthropic/claude-sonnet-4-5-20250929"
    assert response.usage["total_tokens"] == 15
    assert response.latency_ms >= 0
    assert captured_kwargs["extra_headers"]["X-Request-ID"] == "req-llm-1"
    assert (
        captured_kwargs["extra_headers"]["traceparent"]
        == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    )
    clear_tracing_context()


def test_get_llm_provider_routes_gpt_models_to_litellm_by_default():
    settings = SimpleNamespace(llm=LLMConfig(provider="gpt-4o-mini"))
    provider = get_llm_provider(settings=settings)
    assert isinstance(provider, LiteLLMProvider)


def test_get_llm_provider_routes_explicit_ollama_provider_to_ollama():
    settings = SimpleNamespace(llm=LLMConfig(provider="ollama/llama3.2"))
    provider = get_llm_provider(settings=settings)
    assert isinstance(provider, OllamaProvider)


def test_get_llm_provider_routes_ollama_host_to_ollama():
    settings = SimpleNamespace(llm=LLMConfig(provider="gpt-oss:20b", base_url="https://ollama.com"))
    provider = get_llm_provider(settings=settings)
    assert isinstance(provider, OllamaProvider)
