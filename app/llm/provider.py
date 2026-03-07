"""LLM chat provider — OpenAI-compatible /chat/completions API.

Supports any OpenAI-compatible endpoint (OpenAI, Azure, local proxies).
Embeddings are handled independently via VECTOR_* settings.
"""

from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from typing import Any

import httpx
import structlog
from langchain_core.messages import AIMessage, BaseMessage

from app.core.config import Settings, get_settings
from app.core.tracing import get_tracing_headers

logger = structlog.get_logger(__name__)

# Max retries on empty-content responses.
_MAX_CONTENT_RETRIES = 3
_RETRY_DELAY_SECONDS = 1.0

# Max retries on transient HTTP errors (429, 502, 503, 504).
_MAX_HTTP_RETRIES = 3
_HTTP_RETRY_BACKOFF_BASE = 2.0  # exponential: 2s, 4s, 8s
_RETRYABLE_STATUS_CODES = frozenset({429, 502, 503, 504})
_REASONING_MODEL_PREFIXES = ("gpt-5", "o1", "o3", "o4")
_DEFAULT_REASONING_EFFORT = "minimal"


def _extract_text_field(value: Any) -> str:
    """Normalize content fields that may be string or structured list."""
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
    """Strip any 'provider/' prefix to get the bare model name."""
    if "/" in provider:
        return provider.split("/", 1)[1]
    return provider


def _is_reasoning_model(model: str) -> bool:
    normalized = model.strip().lower()
    return normalized.startswith(_REASONING_MODEL_PREFIXES)


def _message_role(message: BaseMessage) -> str:
    role = getattr(message, "type", "")
    if role == "system":
        return "system"
    if role == "ai":
        return "assistant"
    return "user"


def _is_valid_json_object(text: str) -> bool:
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        return False
    return isinstance(parsed, dict)


@dataclass(slots=True)
class LLMChatProvider:
    """Async chat provider using OpenAI-compatible /chat/completions API."""

    model: str
    base_url: str
    timeout_seconds: int
    api_key: str
    default_max_tokens: int

    async def _post_with_retries(
        self,
        client: httpx.AsyncClient,
        url: str,
        payload: dict[str, Any],
    ) -> httpx.Response:
        """POST with exponential backoff on transient HTTP errors (429, 5xx)."""
        last_exc: httpx.HTTPStatusError | None = None
        for attempt in range(1, _MAX_HTTP_RETRIES + 1):
            response = await client.post(url, json=payload)
            if response.status_code not in _RETRYABLE_STATUS_CODES:
                response.raise_for_status()
                return response
            last_exc = httpx.HTTPStatusError(
                f"{response.status_code}",
                request=response.request,
                response=response,
            )
            delay = _HTTP_RETRY_BACKOFF_BASE**attempt
            logger.warning(
                "LLM HTTP error; retrying with backoff",
                status_code=response.status_code,
                attempt=attempt,
                max_retries=_MAX_HTTP_RETRIES,
                backoff_seconds=delay,
            )
            await asyncio.sleep(delay)
        raise last_exc  # type: ignore[misc]

    async def ainvoke(self, messages: list[BaseMessage], **kwargs: Any) -> AIMessage:
        max_tokens = int(kwargs.get("max_tokens", self.default_max_tokens))
        request_timeout = float(kwargs.get("request_timeout", self.timeout_seconds))
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
            "max_completion_tokens": max_tokens,
        }
        if _is_reasoning_model(self.model):
            payload["reasoning_effort"] = _DEFAULT_REASONING_EFFORT
        # gpt-5-mini and o-series reasoning models only accept temperature=1 (the default).
        # Always omit temperature so the API uses its default; avoids 400 on restricted models.
        if json_mode:
            payload["response_format"] = {"type": "json_object"}

        headers = {**get_tracing_headers()}
        if self.api_key:
            headers["Authorization"] = f"Bearer {self.api_key}"

        url = f"{self.base_url.rstrip('/')}/chat/completions"
        timeout = httpx.Timeout(request_timeout)
        invalid_json_preview: str | None = None

        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            for attempt in range(1, _MAX_CONTENT_RETRIES + 1):
                response = await self._post_with_retries(client, url, payload)
                data = response.json()

                choices = data.get("choices") or []
                content = ""
                first_choice: dict[str, Any] = {}
                first_message: dict[str, Any] = {}
                if choices:
                    first_choice = choices[0] or {}
                    first_message = (
                        (first_choice.get("message") or {})
                        if isinstance(first_choice, dict)
                        else {}
                    )
                    content = _extract_text_field(first_message.get("content") or "")

                if content:
                    if not json_mode or _is_valid_json_object(content):
                        usage = data.get("usage") or {}
                        return AIMessage(
                            content=content,
                            usage_metadata={
                                "input_tokens": int(usage.get("prompt_tokens", 0)),
                                "output_tokens": int(usage.get("completion_tokens", 0)),
                                "total_tokens": int(usage.get("total_tokens", 0)),
                            },
                            response_metadata={"model": str(data.get("model", self.model))},
                        )
                    invalid_json_preview = content[:240]
                    logger.warning(
                        "LLM returned non-JSON in json_mode",
                        attempt=attempt,
                        max_retries=_MAX_CONTENT_RETRIES,
                        content_preview=invalid_json_preview,
                    )
                else:
                    usage = data.get("usage") if isinstance(data, dict) else {}
                    completion_tokens = int((usage or {}).get("completion_tokens", 0))
                    completion_details = (usage or {}).get("completion_tokens_details") or {}
                    reasoning_tokens = int((completion_details or {}).get("reasoning_tokens", 0))
                    logger.warning(
                        "LLM returned empty content",
                        attempt=attempt,
                        max_retries=_MAX_CONTENT_RETRIES,
                        top_level_keys=sorted(data.keys()) if isinstance(data, dict) else [],
                        finish_reason=first_choice.get("finish_reason"),
                        message_keys=sorted(first_message.keys()) if first_message else [],
                        refusal_present=bool(first_message.get("refusal")),
                        completion_tokens=completion_tokens,
                        reasoning_tokens=reasoning_tokens,
                    )

                if attempt < _MAX_CONTENT_RETRIES:
                    await asyncio.sleep(_RETRY_DELAY_SECONDS)

            if invalid_json_preview is not None:
                raise ValueError(
                    f"LLM non-JSON response after {_MAX_CONTENT_RETRIES} attempts in json_mode; "
                    f"preview={invalid_json_preview!r}"
                )
            raise ValueError(f"LLM returned empty content after {_MAX_CONTENT_RETRIES} attempts")


def get_chat_model(settings: Settings | None = None) -> LLMChatProvider:
    """Return the configured LLM chat provider."""
    active = settings or get_settings()
    llm_config = active.llm
    return LLMChatProvider(
        model=_provider_to_model(llm_config.provider),
        base_url=llm_config.base_url,
        timeout_seconds=llm_config.timeout,
        api_key=llm_config.api_key.get_secret_value(),
        default_max_tokens=llm_config.max_completion_tokens,
    )
