"""Unit tests for LLM chat provider."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.llm.provider import LLMChatProvider


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


def _openai_response(content: str, model: str = "gpt-5-mini") -> dict:
    """Minimal OpenAI-compatible /chat/completions response."""
    return {
        "model": model,
        "choices": [{"message": {"role": "assistant", "content": content}}],
        "usage": {"prompt_tokens": 10, "completion_tokens": 12, "total_tokens": 22},
    }


def _make_provider(**kwargs) -> LLMChatProvider:
    defaults = dict(
        model="gpt-5-mini",
        base_url="https://api.openai.com/v1",
        timeout_seconds=10,
        api_key="sk-test",
        default_max_tokens=128,
    )
    return LLMChatProvider(**{**defaults, **kwargs})


@pytest.mark.asyncio
async def test_ainvoke_returns_response(monkeypatch):
    model = _make_provider()

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        return _FakeResponse(_openai_response('{"risk_level":"LOW","confidence":0.9}'))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    response = await model.ainvoke([HumanMessage(content="analyse this")])

    assert '"risk_level":"LOW"' in response.content
    assert response.usage_metadata["total_tokens"] == 22
    assert response.response_metadata["model"] == "gpt-5-mini"


@pytest.mark.asyncio
async def test_ainvoke_sets_minimal_reasoning_effort_for_reasoning_models(monkeypatch):
    model = _make_provider(model="gpt-5-mini")
    captured_payload: dict = {}

    async def fake_post(self, _client, _url, payload):  # noqa: ANN001
        captured_payload.update(payload)
        return _FakeResponse(_openai_response('{"risk_level":"LOW"}'))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    await model.ainvoke([HumanMessage(content="test")])

    assert captured_payload["reasoning_effort"] == "minimal"


@pytest.mark.asyncio
async def test_ainvoke_skips_reasoning_effort_for_non_reasoning_models(monkeypatch):
    model = _make_provider(model="gpt-4.1-mini")
    captured_payload: dict = {}

    async def fake_post(self, _client, _url, payload):  # noqa: ANN001
        captured_payload.update(payload)
        return _FakeResponse(_openai_response('{"risk_level":"LOW"}', model="gpt-4.1-mini"))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    await model.ainvoke([HumanMessage(content="test")])

    assert "reasoning_effort" not in captured_payload


@pytest.mark.asyncio
async def test_ainvoke_retries_on_empty_content(monkeypatch):
    model = _make_provider()
    calls = 0

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        nonlocal calls
        calls += 1
        if calls < 3:
            return _FakeResponse({"model": "gpt-5-mini", "choices": [{"message": {"content": ""}}]})
        return _FakeResponse(_openai_response('{"risk_level":"LOW"}'))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    response = await model.ainvoke([HumanMessage(content="test")])
    assert '"risk_level":"LOW"' in response.content
    assert calls == 3


@pytest.mark.asyncio
async def test_ainvoke_raises_after_max_retries_empty(monkeypatch):
    model = _make_provider()

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        return _FakeResponse({"model": "gpt-5-mini", "choices": [{"message": {"content": ""}}]})

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    with pytest.raises(ValueError, match="empty content"):
        await model.ainvoke([HumanMessage(content="test")])


@pytest.mark.asyncio
async def test_ainvoke_raises_on_non_json_in_json_mode(monkeypatch):
    model = _make_provider()

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        return _FakeResponse(_openai_response("here is your answer in plain text"))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    with pytest.raises(ValueError, match="non-JSON"):
        await model.ainvoke([HumanMessage(content="test")], json_mode=True)


@pytest.mark.asyncio
async def test_ainvoke_non_json_mode_accepts_plain_text(monkeypatch):
    model = _make_provider()

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        return _FakeResponse(_openai_response("plain text response"))

    monkeypatch.setattr(LLMChatProvider, "_post_with_retries", fake_post)

    response = await model.ainvoke([HumanMessage(content="test")], json_mode=False)
    assert response.content == "plain text response"
