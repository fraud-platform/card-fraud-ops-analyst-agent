"""Unit tests for tracing context helpers."""

from app.core.tracing import (
    bind_contextvars_to_logging,
    clear_tracing_context,
    get_current_trace_id,
    get_request_id,
    get_trace_parent,
    get_tracing_headers,
    set_request_id,
    set_trace_parent,
)


def test_set_request_id_generates_when_missing():
    clear_tracing_context()
    set_request_id(None)
    assert get_request_id() is not None


def test_set_trace_parent_can_clear_value():
    set_trace_parent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
    assert get_trace_parent() is not None
    set_trace_parent(None)
    assert get_trace_parent() is None


def test_get_tracing_headers_includes_request_id_and_traceparent():
    clear_tracing_context()
    set_request_id("req-123")
    set_trace_parent("00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01")
    headers = get_tracing_headers()
    assert headers["X-Request-ID"] == "req-123"
    assert headers["traceparent"] == "00-aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa-bbbbbbbbbbbbbbbb-01"


def test_bind_contextvars_to_logging_returns_expected_keys():
    clear_tracing_context()
    set_request_id("req-xyz")
    set_trace_parent("00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01")
    ctx = bind_contextvars_to_logging()
    assert ctx["request_id"] == "req-xyz"
    assert ctx["trace_parent"] == "00-cccccccccccccccccccccccccccccccc-dddddddddddddddd-01"


def test_clear_tracing_context_resets_headers():
    set_request_id("req-to-clear")
    set_trace_parent("00-eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee-ffffffffffffffff-01")
    clear_tracing_context()
    assert get_request_id() is None
    assert get_trace_parent() is None
    assert get_tracing_headers() == {}


def test_get_current_trace_id_returns_none_without_valid_span():
    assert get_current_trace_id() is None


def test_get_current_trace_id_renders_otel_trace_id(monkeypatch):
    class _SpanContext:
        is_valid = True
        trace_id = int("0123456789abcdef0123456789abcdef", 16)

    class _Span:
        @staticmethod
        def get_span_context():
            return _SpanContext()

    monkeypatch.setattr("app.core.tracing.otel_trace.get_current_span", lambda: _Span())
    assert get_current_trace_id() == "0123456789abcdef0123456789abcdef"
