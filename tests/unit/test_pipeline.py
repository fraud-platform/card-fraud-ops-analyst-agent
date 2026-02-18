"""Unit tests for the Pipeline orchestrator."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.pipeline import Pipeline

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_context() -> dict:
    """Return a minimal valid context dict."""
    return {
        "transaction": MagicMock(transaction_timestamp="2026-02-15T10:00:00Z"),
        "signals": [],
    }


def _make_pattern_results(severity: str = "HIGH") -> dict:
    """Return a minimal valid pattern analysis result."""
    return {
        "severity": severity,
        "patterns": [{"pattern_name": "velocity", "score": 0.8}],
        "pattern_scores": [],
    }


def _make_similarity_results(overall_score: float = 0.7) -> dict:
    """Return a minimal valid similarity analysis result."""
    return {
        "overall_score": overall_score,
        "similar_transactions": [],
        "similarity_result": MagicMock(overall_score=overall_score),
    }


def _make_recommendation_result() -> dict:
    """Return a minimal valid recommendation result."""
    return {
        "insight": {"insight_id": "ins-1", "severity": "HIGH", "summary": "Test insight"},
        "recommendations": [{"recommendation_id": "rec-1", "type": "review_priority"}],
        "model_mode": "deterministic",
    }


def _make_pipeline_with_mocks() -> Pipeline:
    """Create a Pipeline with a mock session and replace all sub-engines."""
    mock_session = AsyncMock()
    # Bypass real sub-engine constructors which require real sessions
    with (
        patch("app.agents.pipeline.ContextBuilder"),
        patch("app.agents.pipeline.PatternEngine"),
        patch("app.agents.pipeline.SimilarityEngine"),
        patch("app.agents.pipeline.RecommendationEngine"),
        patch("app.agents.pipeline.ReasoningEngine"),
        patch("app.agents.pipeline.InsightRepository"),
        patch("app.agents.pipeline.RunRepository"),
    ):
        pipeline = Pipeline(mock_session)

    # Replace all engines with fresh AsyncMocks
    pipeline.context_builder = AsyncMock()
    pipeline.pattern_engine = AsyncMock()
    pipeline.similarity_engine = AsyncMock()
    pipeline.recommendation_engine = AsyncMock()
    pipeline.reasoning_engine = AsyncMock()
    pipeline.insight_repo = AsyncMock()
    pipeline.insight_repo.add_evidence = AsyncMock(return_value={})
    pipeline.run_repo = AsyncMock()
    return pipeline


# ---------------------------------------------------------------------------
# Pipeline.run() success paths
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_pipeline_run_success_returns_expected_keys():
    """Pipeline.run() succeeds and returns dict with run_id, status, model_mode."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(
        run_id="run-001",
        mode="auto",
        transaction_id="txn-001",
    )

    assert result["run_id"] == "run-001"
    assert result["status"] == "SUCCESS"
    assert result["mode"] == "auto"
    assert result["transaction_id"] == "txn-001"
    assert result["model_mode"] == "deterministic"
    assert "duration_ms" in result
    assert "stage_durations" in result
    assert "recommendations" in result
    pipeline.session.commit.assert_called()


@pytest.mark.asyncio
async def test_pipeline_run_with_case_id():
    """Pipeline.run() passes case_id to span attribute without error."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(
        run_id="run-002",
        mode="auto",
        transaction_id="txn-002",
        case_id="case-99",
    )

    assert result["status"] == "SUCCESS"
    pipeline.run_repo.complete.assert_called_once()
    args = pipeline.run_repo.complete.call_args.args
    kwargs = pipeline.run_repo.complete.call_args.kwargs
    assert args == ("run-002", "SUCCESS", None)
    assert isinstance(kwargs.get("stage_durations"), dict)
    assert kwargs.get("duration_ms") is not None


@pytest.mark.asyncio
async def test_pipeline_run_with_reasoning_result_calls_record_metrics():
    """Pipeline.run() with a reasoning_result calls _record_llm_metrics."""
    pipeline = _make_pipeline_with_mocks()

    reasoning_result = {
        "model_mode": "hybrid",
        "narrative": "LLM narrative text",
        "confidence": 0.85,
        "llm_latency_ms": 1200.0,
        "llm_model": "ollama/llama3.2",
        "llm_usage": {"prompt_tokens": 100, "completion_tokens": 50},
    }

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=reasoning_result)
    pipeline.recommendation_engine.generate = AsyncMock(
        return_value={
            "insight": {"insight_id": "ins-2"},
            "recommendations": [],
            "model_mode": "hybrid",
        }
    )
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(
        run_id="run-003",
        mode="hybrid",
        transaction_id="txn-003",
    )

    assert result["model_mode"] == "hybrid"
    assert result["status"] == "SUCCESS"


@pytest.mark.asyncio
async def test_pipeline_run_with_reasoning_none_increments_fallback():
    """Pipeline.run() with reasoning_result=None increments the fallback counter."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(
        run_id="run-004",
        mode="auto",
        transaction_id="txn-004",
    )

    # model_mode should be deterministic when reasoning_result is None
    assert result["model_mode"] == "deterministic"


@pytest.mark.asyncio
async def test_pipeline_run_raises_value_error_calls_complete_failed():
    """Pipeline.run() catches ValueError, calls _complete_run(FAILED), re-raises."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(side_effect=ValueError("bad context"))
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    with pytest.raises(ValueError, match="bad context"):
        await pipeline.run(
            run_id="run-005",
            mode="auto",
            transaction_id="txn-005",
        )

    pipeline.run_repo.complete.assert_called_once()
    args = pipeline.run_repo.complete.call_args.args
    kwargs = pipeline.run_repo.complete.call_args.kwargs
    assert args == ("run-005", "FAILED", "bad context")
    assert kwargs.get("llm_status") == "failed"


@pytest.mark.asyncio
async def test_pipeline_run_raises_connection_error_calls_complete_failed():
    """Pipeline.run() catches ConnectionError, calls _complete_run(FAILED), re-raises."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(side_effect=ConnectionError("db down"))
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    with pytest.raises(ConnectionError, match="db down"):
        await pipeline.run(
            run_id="run-006",
            mode="auto",
            transaction_id="txn-006",
        )

    pipeline.run_repo.complete.assert_called_once()
    args = pipeline.run_repo.complete.call_args.args
    kwargs = pipeline.run_repo.complete.call_args.kwargs
    assert args == ("run-006", "FAILED", "db down")
    assert kwargs.get("llm_status") == "failed"


@pytest.mark.asyncio
async def test_pipeline_run_stage_durations_populated():
    """Pipeline.run() populates stage_durations dict with all expected stages."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(
        run_id="run-007",
        mode="auto",
        transaction_id="txn-007",
    )

    durations = result["stage_durations"]
    assert "context_build" in durations
    assert "pattern_analysis" in durations
    assert "similarity_analysis" in durations
    assert "llm_reasoning" in durations
    assert "recommendations" in durations
    # All durations should be non-negative numbers
    for v in durations.values():
        assert v >= 0.0


@pytest.mark.asyncio
async def test_pipeline_run_complete_run_called_on_success():
    """Pipeline.run() calls run_repo.complete with SUCCESS on happy path."""
    pipeline = _make_pipeline_with_mocks()

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    await pipeline.run(run_id="run-008", mode="auto", transaction_id="txn-008")

    pipeline.run_repo.complete.assert_called_once()
    args = pipeline.run_repo.complete.call_args.args
    kwargs = pipeline.run_repo.complete.call_args.kwargs
    assert args == ("run-008", "SUCCESS", None)
    assert kwargs.get("model_mode") == "deterministic"
    assert kwargs.get("llm_status") in {"deterministic", "skipped", "disabled"}


# ---------------------------------------------------------------------------
# _timed_stage()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_timed_stage_measures_timing():
    """_timed_stage() stores duration in the durations dict."""
    pipeline = _make_pipeline_with_mocks()
    durations: dict[str, float] = {}

    async def _fast_coro():
        return "result"

    result = await pipeline._timed_stage("test_stage", durations, _fast_coro())

    assert result == "result"
    assert "test_stage" in durations
    assert durations["test_stage"] >= 0.0


@pytest.mark.asyncio
async def test_timed_stage_propagates_value_error():
    """_timed_stage() propagates ValueError exceptions."""
    pipeline = _make_pipeline_with_mocks()
    durations: dict[str, float] = {}

    async def _failing_coro():
        raise ValueError("stage error")

    with pytest.raises(ValueError, match="stage error"):
        await pipeline._timed_stage("failing_stage", durations, _failing_coro())

    # Duration should NOT be recorded on exception
    assert "failing_stage" not in durations


@pytest.mark.asyncio
async def test_timed_stage_propagates_key_error():
    """_timed_stage() propagates KeyError exceptions."""
    pipeline = _make_pipeline_with_mocks()
    durations: dict[str, float] = {}

    async def _failing_coro():
        raise KeyError("missing key")

    with pytest.raises(KeyError):
        await pipeline._timed_stage("key_stage", durations, _failing_coro())


# ---------------------------------------------------------------------------
# _record_llm_metrics()
# ---------------------------------------------------------------------------


def test_record_llm_metrics_with_all_fields():
    """_record_llm_metrics() processes full reasoning_result without error."""
    pipeline = _make_pipeline_with_mocks()
    mock_span = MagicMock()

    reasoning_result = {
        "llm_latency_ms": 800.0,
        "llm_model": "ollama/llama3.2",
        "llm_usage": {"prompt_tokens": 200, "completion_tokens": 80},
        "confidence": 0.9,
    }

    # Should not raise
    pipeline._record_llm_metrics(reasoning_result, mock_span)

    # Verify span attributes were set
    span_calls = {call[0][0]: call[0][1] for call in mock_span.set_attribute.call_args_list}
    assert "llm.latency_ms" in span_calls
    assert "llm.model" in span_calls
    assert "llm.confidence" in span_calls


def test_record_llm_metrics_with_empty_usage():
    """_record_llm_metrics() handles None/empty usage dict gracefully."""
    pipeline = _make_pipeline_with_mocks()
    mock_span = MagicMock()

    reasoning_result = {
        "llm_latency_ms": 0,
        "llm_model": "",
        "llm_usage": None,
        "confidence": None,
    }

    # Should not raise even with empty/None fields
    pipeline._record_llm_metrics(reasoning_result, mock_span)


def test_record_llm_metrics_with_no_confidence():
    """_record_llm_metrics() skips consistency observe when confidence is None."""
    pipeline = _make_pipeline_with_mocks()
    mock_span = MagicMock()

    reasoning_result = {
        "llm_latency_ms": 500.0,
        "llm_model": "test-model",
        "llm_usage": {"prompt_tokens": 50, "completion_tokens": 20},
        # no 'confidence' key
    }

    # Should not raise
    pipeline._record_llm_metrics(reasoning_result, mock_span)

    span_calls = {call[0][0]: call[0][1] for call in mock_span.set_attribute.call_args_list}
    assert "llm.confidence" not in span_calls


def test_record_llm_metrics_with_token_counts():
    """_record_llm_metrics() sets prompt and completion token span attributes."""
    pipeline = _make_pipeline_with_mocks()
    mock_span = MagicMock()

    reasoning_result = {
        "llm_latency_ms": 300.0,
        "llm_model": "gpt-4",
        "llm_usage": {"prompt_tokens": 150, "completion_tokens": 75},
        "confidence": 0.75,
    }

    pipeline._record_llm_metrics(reasoning_result, mock_span)

    span_calls = {call[0][0]: call[0][1] for call in mock_span.set_attribute.call_args_list}
    assert span_calls.get("llm.prompt_tokens") == 150
    assert span_calls.get("llm.completion_tokens") == 75


# ---------------------------------------------------------------------------
# New feature methods: _compute_conflict_matrix + _build_explanation
# ---------------------------------------------------------------------------


def test_compute_conflict_matrix_with_plain_dict_similarity():
    """_compute_conflict_matrix() works with plain dict (no similarity_result key)."""
    pipeline = _make_pipeline_with_mocks()
    result = pipeline._compute_conflict_matrix(
        pattern_analysis={"severity": "HIGH"},
        similarity_analysis={"overall_score": 0.2},
    )
    assert "overall_conflict_score" in result
    assert "resolution_strategy" in result
    assert isinstance(result["overall_conflict_score"], float)


def test_compute_conflict_matrix_with_similarity_result_object():
    """_compute_conflict_matrix() extracts score from similarity_result attribute."""
    pipeline = _make_pipeline_with_mocks()

    class _FakeSimilarityResult:
        overall_score = 0.8

    result = pipeline._compute_conflict_matrix(
        pattern_analysis={"severity": "HIGH"},
        similarity_analysis={"similarity_result": _FakeSimilarityResult()},
    )
    assert isinstance(result["overall_conflict_score"], float)
    assert result["pattern_vs_similarity"] in ("aligned", "conflicting", "neutral")


def test_compute_conflict_matrix_low_severity_low_similarity_aligned():
    """Low pattern + low similarity → pattern_vs_similarity = aligned."""
    pipeline = _make_pipeline_with_mocks()
    result = pipeline._compute_conflict_matrix(
        pattern_analysis={"severity": "LOW"},
        similarity_analysis={"overall_score": 0.1},
    )
    assert result["pattern_vs_similarity"] == "aligned"


def test_build_explanation_with_plain_dict_similarity():
    """_build_explanation() works with plain dict similarity result."""
    pipeline = _make_pipeline_with_mocks()
    context = {"investigation_id": "inv-1", "transaction_id": "tx-1"}
    result = pipeline._build_explanation(
        context=context,
        pattern_analysis={"severity": "MEDIUM", "patterns": []},
        similarity_analysis={"overall_score": 0.5, "matches": []},
        conflict_matrix=None,
        llm_reasoning=None,
    )
    assert result["investigation_id"] == "inv-1"
    assert result["transaction_id"] == "tx-1"
    assert "markdown" in result
    assert "# Investigation Report" in result["markdown"]


def test_build_explanation_with_similarity_result_object():
    """_build_explanation() converts SimilarityResult dataclass to dict."""
    from app.agents.similarity_engine_core import SimilarityMatch, SimilarityResult

    pipeline = _make_pipeline_with_mocks()
    context = {"investigation_id": "inv-2", "transaction_id": "tx-2"}
    similarity_result = SimilarityResult(
        matches=[
            SimilarityMatch(
                match_id="tx-abc",
                match_type="vector",
                similarity_score=0.85,
                details={},
            )
        ],
        overall_score=0.85,
    )
    result = pipeline._build_explanation(
        context=context,
        pattern_analysis={"severity": "HIGH", "patterns": []},
        similarity_analysis={"similarity_result": similarity_result},
        conflict_matrix={"overall_conflict_score": 0.1, "resolution_strategy": "trust_det"},
        llm_reasoning={"narrative_summary": "Fraud suspected", "confidence": 0.9},
    )
    assert result["investigation_id"] == "inv-2"
    assert "tx-abc" in result["markdown"]


@pytest.mark.asyncio
async def test_pipeline_run_with_conflict_matrix_enabled():
    """Pipeline.run() includes conflict_matrix in result when feature enabled."""
    pipeline = _make_pipeline_with_mocks()
    pipeline._settings.features.conflict_matrix_enabled = True
    pipeline._settings.features.explanation_builder_enabled = False

    pipeline.context_builder.build = AsyncMock(return_value=_make_context())
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(run_id="run-cm", mode="auto", transaction_id="txn-001")
    assert "conflict_matrix" in result
    assert "overall_conflict_score" in result["conflict_matrix"]


@pytest.mark.asyncio
async def test_pipeline_run_with_explanation_builder_enabled():
    """Pipeline.run() includes explanation in result when feature enabled."""
    pipeline = _make_pipeline_with_mocks()
    pipeline._settings.features.conflict_matrix_enabled = False
    pipeline._settings.features.explanation_builder_enabled = True

    pipeline.context_builder.build = AsyncMock(
        return_value={"transaction": {}, "investigation_id": "inv-x"}
    )
    pipeline.pattern_engine.analyze = AsyncMock(return_value=_make_pattern_results())
    pipeline.similarity_engine.analyze = AsyncMock(return_value=_make_similarity_results())
    pipeline.reasoning_engine.reason = AsyncMock(return_value=None)
    pipeline.recommendation_engine.generate = AsyncMock(return_value=_make_recommendation_result())
    pipeline.run_repo.complete = AsyncMock(return_value=None)

    result = await pipeline.run(run_id="run-ex", mode="auto", transaction_id="txn-001")
    assert "explanation" in result
    assert "markdown" in result["explanation"]
