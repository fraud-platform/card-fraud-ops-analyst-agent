"""Ollama Cloud chat model adapter used by planner and reasoning stages.

This module intentionally supports a single provider path:
- Ollama Cloud for planner/reasoning chat completions.

Embeddings remain independently configured via VECTOR_* settings.
"""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from langchain_core.messages import AIMessage, BaseMessage

from app.core.config import Settings, get_settings
from app.core.tracing import get_tracing_headers

logger = structlog.get_logger(__name__)

# Max retries on empty-content responses (gpt-oss thinking model intermittently
# returns empty content under concurrent load).
_MAX_CONTENT_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0

# Max retries on transient HTTP errors (429, 502, 503, 504).
_MAX_HTTP_RETRIES = 3
_HTTP_RETRY_BACKOFF_BASE = 2.0  # exponential: 2s, 4s, 8s
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})


def _extract_text_field(value: Any) -> str:
    """Normalize provider text fields that may be string or structured list."""
    if isinstance(value, str):
        return value.strip()
    if not isinstance(value, list):
        return ""
    parts: list[str] = []
    for item in value:
        if isinstance(item, str):
            parts.append(item)
            continue
        if isinstance(item, dict):
            text = item.get("text")
            if isinstance(text, str):
                parts.append(text)
    return "".join(parts).strip()


def _provider_to_model(provider: str) -> str:
    if provider.startswith(("ollama/", "ollama_chat/")):
        return provider.split("/", 1)[1]
    return provider


def _api_base(base_url: str) -> str:
    normalized = base_url.strip().rstrip("/")
    if normalized.endswith("/api"):
        return normalized
    return f"{normalized}/api"


def _message_role(message: BaseMessage) -> str:
    role = getattr(message, "type", "")
    if role == "system":
        return "system"
    if role == "ai":
        return "assistant"
    return "user"


@dataclass(slots=True)
class OllamaCloudChatModel:
    """Minimal async chat model adapter exposing ``ainvoke``."""

    model: str
    base_url: str
    timeout_seconds: int
    api_key: str
    default_temperature: float
    default_max_tokens: int

    async def _post_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """POST with exponential backoff on transient HTTP errors (429, 5xx)."""
        last_exc: httpx.HTTPStatusError | None = None
        for http_attempt in range(1, _MAX_HTTP_RETRIES + 1):
            response = await client.post(url, json=payload)
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = httpx.HTTPStatusError(
                f"{response.status_code}",
                request=response.request,
                response=response,
            )
            delay = _HTTP_RETRY_BACKOFF_BASE**http_attempt
            logger.warning(
                "Ollama HTTP error; retrying with backoff",
                status_code=response.status_code,
                attempt=http_attempt,
                max_retries=_MAX_HTTP_RETRIES,
                backoff_seconds=delay,
            )
            await asyncio.sleep(delay)
        # All retries exhausted — raise the last error
        raise last_exc  # type: ignore[misc]

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        temperature = float(kwargs.get("temperature", self.default_temperature))
        max_tokens = int(kwargs.get("max_tokens", self.default_max_tokens))
        json_mode = bool(kwargs.get("json_mode", True))

        payload_messages = [
            {
                "role": _message_role(message),
                "content": str(getattr(message, "content", "")),
            }
            for message in messages
        ]

        payload: dict[str, Any] = {
            "model": self.model,
            "messages": payload_messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        headers = {**get_tracing_headers()}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        timeout = httpx.Timeout(float(self.timeout_seconds))
        data: dict[str, Any] = {}
        content: str | None = None
        fallback_thinking: str | None = None
        fallback_response: str | None = None
        message_keys: list[str] = []
        url = f"{_api_base(self.base_url)}/chat"
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            for attempt in range(1, _MAX_CONTENT_RETRIES + 1):
                response = await self._post_with_retries(client, url, payload)
                data = response.json()

                message_obj = data.get("message")
                raw_content = message_obj.get("content") if isinstance(message_obj, dict) else None
                raw_thinking = (
                    message_obj.get("thinking") if isinstance(message_obj, dict) else None
                )
                content_text = _extract_text_field(raw_content)
                thinking_text = _extract_text_field(raw_thinking)
                response_text = _extract_text_field(data.get("response"))

                if content_text:
                    content = content_text
                    break

                if thinking_text:
                    fallback_thinking = thinking_text
                if response_text:
                    fallback_response = response_text

                if fallback_response:
                    # Some providers return top-level `response` instead of message.content.
                    content = fallback_response
                    logger.warning(
                        "Ollama returned empty message.content; using top-level response fallback",
                        attempt=attempt,
                        max_retries=_MAX_CONTENT_RETRIES,
                    )
                    break

                if fallback_thinking and attempt == _MAX_CONTENT_RETRIES:
                    # Final fallback: preserve thinking text rather than raising transport error.
                    content = fallback_thinking
                    logger.warning(
                        "Ollama returned empty message.content; using message.thinking fallback",
                        attempt=attempt,
                        max_retries=_MAX_CONTENT_RETRIES,
                        thinking_chars=len(fallback_thinking),
                    )
                    break

                message_keys = sorted(message_obj.keys()) if isinstance(message_obj, dict) else []
                logger.warning(
                    "Ollama returned empty message.content",
                    attempt=attempt,
                    max_retries=_MAX_CONTENT_RETRIES,
                    message_keys=message_keys,
                    thinking_chars=len(str(message_obj.get("thinking", "")))
                    if isinstance(message_obj, dict)
                    else 0,
                    top_level_keys=sorted(data.keys()) if isinstance(data, dict) else [],
                )
                if attempt < _MAX_CONTENT_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)
            else:
                raise ValueError(
                    f"Ollama empty message.content after {_MAX_CONTENT_RETRIES} attempts; "
                    f"top_keys={sorted(data.keys())} message_keys={message_keys}"
                )

        content = str(content)

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        usage_metadata = {
            "input_tokens": prompt_tokens,
            "output_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }
        response_metadata = {
            "model": str(data.get("model") or self.model),
            "done_reason": data.get("done_reason"),
        }
        return AIMessage(
            content=content,
            usage_metadata=usage_metadata,
            response_metadata=response_metadata,
        )


def get_chat_model(settings: Settings | None = None) -> OllamaCloudChatModel:
    """Return the configured Ollama Cloud chat model adapter."""
    active = settings or get_settings()
    llm_config = active.llm
    planner_config = active.planner
    return OllamaCloudChatModel(
        model=_provider_to_model(llm_config.provider),
        base_url=llm_config.base_url,
        timeout_seconds=llm_config.timeout,
        api_key=llm_config.api_key.get_secret_value(),
        default_temperature=planner_config.temperature,
        default_max_tokens=llm_config.max_completion_tokens,
    )
