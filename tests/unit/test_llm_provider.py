"""Unit tests for Ollama cloud chat provider adapter."""

from __future__ import annotations

import pytest
from langchain_core.messages import HumanMessage

from app.llm.provider import OllamaCloudChatModel


class _FakeResponse:
    def __init__(self, payload: dict) -> None:
        self._payload = payload

    def json(self) -> dict:
        return self._payload


@pytest.mark.asyncio
async def test_ainvoke_uses_thinking_fallback_when_content_empty(monkeypatch):
    model = OllamaCloudChatModel(
        model="gpt-oss:20b",
        base_url="https://ollama.com",
        timeout_seconds=10,
        api_key="",
        default_temperature=0.1,
        default_max_tokens=128,
    )

    calls = 0

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return _FakeResponse(
            {
                "model": "gpt-oss:20b",
                "message": {
                    "role": "assistant",
                    "content": "",
                    "thinking": "fallback thinking text",
                },
                "prompt_eval_count": 10,
                "eval_count": 12,
            }
        )

    monkeypatch.setattr(OllamaCloudChatModel, "_post_with_retries", fake_post)

    response = await model.ainvoke([HumanMessage(content="test")])

    assert response.content == "fallback thinking text"
    assert calls == 3
    assert response.usage_metadata["total_tokens"] == 22


@pytest.mark.asyncio
async def test_ainvoke_uses_top_level_response_fallback(monkeypatch):
    model = OllamaCloudChatModel(
        model="gpt-oss:20b",
        base_url="https://ollama.com",
        timeout_seconds=10,
        api_key="",
        default_temperature=0.1,
        default_max_tokens=128,
    )

    calls = 0

    async def fake_post(self, _client, _url, _payload):  # noqa: ANN001
        nonlocal calls
        calls += 1
        return _FakeResponse(
            {
                "model": "gpt-oss:20b",
                "response": '{"narrative":"ok","risk_level":"LOW","key_findings":[],"hypotheses":[],"confidence":0.5}',
                "message": {"role": "assistant", "content": ""},
                "prompt_eval_count": 5,
                "eval_count": 9,
            }
        )

    monkeypatch.setattr(OllamaCloudChatModel, "_post_with_retries", fake_post)

    response = await model.ainvoke([HumanMessage(content="test")])

    assert '"risk_level":"LOW"' in response.content
    assert calls == 1
