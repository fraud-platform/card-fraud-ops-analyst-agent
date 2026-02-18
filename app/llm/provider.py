"""LLM provider abstraction.

This project supports two LLM execution backends:
- Native Ollama HTTP API (local or https://ollama.com Cloud API)
- LiteLLM (kept for compatibility with non-Ollama providers)
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

import httpx

from app.core.config import LLMConfig, Settings, get_settings
from app.core.tracing import get_tracing_headers


@dataclass
class LLMResponse:
    """Structured LLM response."""

    content: str
    model: str
    usage: dict[str, int]
    latency_ms: float


class LLMProvider(ABC):
    """Abstract LLM provider interface."""

    @abstractmethod
    async def complete(
        self,
        messages: list[dict[str, str]],
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate a completion response.

        Args:
            messages: List of message dicts with 'role' and 'content'
            **kwargs: Additional provider-specific parameters

        Returns:
            LLMResponse with content, model, usage, and latency
        """
        ...


class LiteLLMProvider(LLMProvider):
    """LiteLLM wrapper for provider-agnostic LLM calls."""

    def __init__(self, config: LLMConfig):
        self.config = config
        # Lazy import so we can operate in Ollama-only mode.
        import litellm  # type: ignore[import-untyped]

        self._litellm = litellm
        self._litellm.drop_params = True
        self._litellm.set_verbose = False

    async def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        """Generate completion using LiteLLM.

        Args:
            messages: List of message dicts
            json_mode: If True, request JSON response (for Ollama: format="json")
            **kwargs: Additional parameters

        Returns:
            LLMResponse with structured response data
        """
        import time

        start_time = time.perf_counter()

        model = kwargs.pop("model", self.config.provider)
        temperature = kwargs.pop("temperature", 0.1)
        max_tokens = kwargs.pop("max_tokens", self.config.max_completion_tokens)
        timeout = kwargs.pop("timeout", self.config.timeout)
        num_retries = kwargs.pop("num_retries", self.config.max_retries)

        call_kwargs: dict[str, Any] = {}
        if self.config.base_url:
            call_kwargs["api_base"] = self.config.base_url
        if self.config.api_key.get_secret_value():
            call_kwargs["api_key"] = self.config.api_key.get_secret_value()
        tracing_headers = get_tracing_headers()
        if tracing_headers:
            call_kwargs["extra_headers"] = tracing_headers

        # Ollama JSON mode: requires format="json" parameter
        # See: https://docs.litellm.ai/docs/providers/ollama
        if json_mode and model.startswith(("ollama/", "ollama_chat/")):
            call_kwargs["format"] = "json"

        response = await self._litellm.acompletion(
            model=model,
            messages=messages,
            temperature=temperature,
            max_tokens=max_tokens,
            timeout=timeout,
            num_retries=num_retries,
            **call_kwargs,
            **kwargs,
        )

        latency_ms = (time.perf_counter() - start_time) * 1000

        content = response.choices[0].message.content or ""
        usage = {
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        }

        return LLMResponse(
            content=content,
            model=response.model,
            usage=usage,
            latency_ms=latency_ms,
        )


def _ollama_model_name(provider: str) -> str:
    # Allow both LiteLLM-style strings (ollama/..., ollama_chat/...) and raw
    # Ollama model names (gpt-oss:120b-cloud).
    if provider.startswith(("ollama/", "ollama_chat/")):
        return provider.split("/", 1)[1]
    return provider


def _ollama_api_base(base_url: str) -> str:
    base = base_url.rstrip("/")
    if base.endswith("/api"):
        return base
    return f"{base}/api"


class OllamaProvider(LLMProvider):
    """Native Ollama HTTP API provider.

    Works with both local Ollama (default host http://localhost:11434)
    and Ollama Cloud API (host https://ollama.com with Bearer auth).
    """

    def __init__(self, config: LLMConfig):
        self.config = config

    async def complete(
        self,
        messages: list[dict[str, str]],
        json_mode: bool = False,
        **kwargs: Any,
    ) -> LLMResponse:
        import time

        start_time = time.perf_counter()

        provider_model = kwargs.pop("model", self.config.provider)
        model = _ollama_model_name(provider_model)

        temperature = kwargs.pop("temperature", 0.1)
        max_tokens = kwargs.pop("max_tokens", self.config.max_completion_tokens)
        timeout_s = kwargs.pop("timeout", self.config.timeout)

        host = (self.config.base_url or "http://localhost:11434").rstrip("/")
        api_base = _ollama_api_base(host)
        url = f"{api_base}/chat"

        headers: dict[str, str] = {}

        # Add distributed tracing headers for request correlation
        headers.update(get_tracing_headers())

        api_key = self.config.api_key.get_secret_value()
        if api_key:
            headers["Authorization"] = f"Bearer {api_key}"

        payload: dict[str, Any] = {
            "model": model,
            "messages": messages,
            "stream": False,
            "options": {
                "temperature": temperature,
                "num_predict": max_tokens,
            },
        }
        if json_mode:
            payload["format"] = "json"

        timeout = httpx.Timeout(float(timeout_s))
        async with httpx.AsyncClient(timeout=timeout, headers=headers) as client:
            response = await client.post(url, json=payload)
            response.raise_for_status()
            data = response.json()

        latency_ms = (time.perf_counter() - start_time) * 1000

        message = data.get("message") or {}
        content = message.get("content")
        if not isinstance(content, str):
            content = ""

        prompt_tokens = int(data.get("prompt_eval_count") or 0)
        completion_tokens = int(data.get("eval_count") or 0)
        usage = {
            "prompt_tokens": prompt_tokens,
            "completion_tokens": completion_tokens,
            "total_tokens": prompt_tokens + completion_tokens,
        }

        return LLMResponse(
            content=content,
            model=str(data.get("model") or model),
            usage=usage,
            latency_ms=latency_ms,
        )


def get_llm_provider(settings: Settings | None = None) -> LLMProvider:
    """Factory function to create LLM provider.

    Args:
        settings: Application settings (defaults to get_settings())

    Returns:
        Configured LLMProvider instance
    """
    if settings is None:
        settings = get_settings()

    provider = settings.llm.provider
    base_url = (settings.llm.base_url or "").lower()
    is_ollama_host = "ollama.com" in base_url or "localhost:11434" in base_url

    if is_ollama_host or provider.startswith(("ollama/", "ollama_chat/")):
        return OllamaProvider(settings.llm)

    return LiteLLMProvider(settings.llm)
