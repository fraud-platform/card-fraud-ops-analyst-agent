"""Unit tests for RuleManagementClient."""

from __future__ import annotations

import httpx
import pytest

from app.clients.rule_management_client import ExportResult, RuleManagementClient
from app.core.tracing import clear_tracing_context, set_request_id, set_trace_parent


class _FakeResponse:
    def __init__(self, status_code: int, json_data: dict | None = None, text: str = ""):
        self.status_code = status_code
        self._json_data = json_data or {}
        self.text = text
        self.content = b"{}"
        self.request = httpx.Request("POST", "http://test")

    def json(self) -> dict:
        return self._json_data

    def raise_for_status(self) -> None:
        if self.status_code >= 400:
            raise httpx.HTTPStatusError("error", request=self.request, response=self)


class _FakeClient:
    def __init__(self, responses: list[_FakeResponse]):
        self._responses = responses
        self.calls = 0
        self.last_headers: dict[str, str] | None = None

    async def post(self, url: str, json: dict, timeout: float, headers: dict | None = None):
        self.calls += 1
        self.last_headers = headers
        return self._responses[min(self.calls - 1, len(self._responses) - 1)]


@pytest.mark.asyncio
async def test_export_draft_success(monkeypatch: pytest.MonkeyPatch):
    client = RuleManagementClient(base_url="http://rm")
    fake = _FakeClient([_FakeResponse(200, {"id": "rule-123"})])

    async def fake_get_client() -> _FakeClient:
        return fake

    async def fake_headers() -> dict[str, str]:
        return {"Content-Type": "application/json"}

    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(client, "_build_headers", fake_headers)

    result = await client.export_draft("/api/v1/import", {"foo": "bar"})

    assert isinstance(result, ExportResult)
    assert result.success is True
    assert result.response_id == "rule-123"
    assert fake.calls == 1


@pytest.mark.asyncio
async def test_export_draft_retries_on_5xx(monkeypatch: pytest.MonkeyPatch):
    client = RuleManagementClient(base_url="http://rm")
    fake = _FakeClient(
        [
            _FakeResponse(500, text="boom"),
            _FakeResponse(502, text="still boom"),
            _FakeResponse(200, {"rule_id": "rule-999"}),
        ]
    )

    class _Attempt:
        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return bool(exc_type and issubclass(exc_type, httpx.RequestError))

    class _Retrying:
        def __aiter__(self):
            self.idx = 0
            return self

        async def __anext__(self):
            if self.idx >= 3:
                raise StopAsyncIteration
            self.idx += 1
            return _Attempt()

    async def fake_get_client() -> _FakeClient:
        return fake

    async def fake_headers() -> dict[str, str]:
        return {"Content-Type": "application/json"}

    monkeypatch.setattr(client, "_get_client", fake_get_client)
    monkeypatch.setattr(client, "_build_headers", fake_headers)
    monkeypatch.setattr("app.clients.rule_management_client.AsyncRetrying", lambda **_: _Retrying())

    result = await client.export_draft("/api/v1/import", {"foo": "bar"})

    assert result.success is True
    assert result.response_id == "rule-999"
    assert fake.calls == 3


@pytest.mark.asyncio
async def test_fetch_m2m_token_returns_none_when_missing_auth(monkeypatch: pytest.MonkeyPatch):
    client = RuleManagementClient(base_url="http://rm")

    monkeypatch.setattr(
        client,
        "_resolve_auth_config",
        lambda: ("", "", "", ""),
    )

    token = await client._fetch_m2m_token()
    assert token is None


@pytest.mark.asyncio
async def test_build_headers_adds_bearer_token(monkeypatch: pytest.MonkeyPatch):
    client = RuleManagementClient(base_url="http://rm")

    async def fake_token() -> str:
        return "abc123"

    monkeypatch.setattr(client, "_fetch_m2m_token", fake_token)

    headers = await client._build_headers()

    assert headers["Content-Type"] == "application/json"
    assert headers["Authorization"] == "Bearer abc123"


@pytest.mark.asyncio
async def test_build_headers_includes_tracing_headers(monkeypatch: pytest.MonkeyPatch):
    client = RuleManagementClient(base_url="http://rm")

    async def fake_token() -> str | None:
        return None

    clear_tracing_context()
    set_request_id("req-rule-client-1")
    set_trace_parent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
    monkeypatch.setattr(client, "_fetch_m2m_token", fake_token)

    headers = await client._build_headers()

    assert headers["X-Request-ID"] == "req-rule-client-1"
    assert headers["traceparent"] == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"
    clear_tracing_context()
