"""Unit tests for RecommendationEngine (DB-bound adapter)."""

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.agents.pattern_engine_core import PatternScore
from app.agents.recommendation_engine import RecommendationEngine

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pattern_score(name: str, score: float) -> PatternScore:
    return PatternScore(pattern_name=name, score=score, weight=1.0, details={})


def _make_similarity_result(overall_score: float = 0.2, matches: list | None = None):
    """Return a MagicMock resembling a SimilarityResult."""
    sr = MagicMock()
    sr.overall_score = overall_score
    sr.matches = matches or []
    return sr


def _make_context() -> dict:
    tx = MagicMock()
    tx.transaction_timestamp = "2026-02-15T10:00:00Z"
    return {"transaction": tx, "signals": []}


def _make_engine() -> RecommendationEngine:
    """Create RecommendationEngine with mocked repos, bypassing real session."""
    with (
        patch("app.agents.recommendation_engine.InsightRepository"),
        patch("app.agents.recommendation_engine.RecommendationRepository"),
    ):
        engine = RecommendationEngine(AsyncMock())

    engine.insight_repo = AsyncMock()
    engine.recommendation_repo = AsyncMock()

    # Defaults
    engine.insight_repo.upsert_insight = AsyncMock(
        return_value={"insight_id": "ins-test", "severity": "HIGH", "summary": "Test"}
    )
    engine.recommendation_repo.upsert_recommendation = AsyncMock(
        return_value={"recommendation_id": "rec-test", "status": "OPEN"}
    )
    return engine


# ---------------------------------------------------------------------------
# generate() — deterministic mode (reasoning=None)
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_deterministic_mode_returns_insight_and_recommendations():
    """generate() with reasoning=None produces deterministic model_mode."""
    engine = _make_engine()

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.8)],
        "severity": "HIGH",
        "patterns": [{"pattern_name": "velocity", "score": 0.8}],
    }
    similarity_analysis = {
        "overall_score": 0.3,
        "similarity_result": _make_similarity_result(0.3),
    }

    result = await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-det-1",
        reasoning=None,
    )

    assert result["model_mode"] == "deterministic"
    assert "insight" in result
    assert "recommendations" in result
    assert isinstance(result["recommendations"], list)


@pytest.mark.asyncio
async def test_generate_calls_upsert_insight():
    """generate() calls insight_repo.upsert_insight exactly once."""
    engine = _make_engine()

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.9)],
        "severity": "CRITICAL",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.8,
        "similarity_result": _make_similarity_result(0.8),
    }

    await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-ins-1",
        reasoning=None,
    )

    engine.insight_repo.upsert_insight.assert_called_once()
    call_kwargs = engine.insight_repo.upsert_insight.call_args[1]
    assert call_kwargs["transaction_id"] == "txn-ins-1"


@pytest.mark.asyncio
async def test_generate_hybrid_mode_merges_narrative():
    """generate() with reasoning dict sets model_mode to 'hybrid'."""
    engine = _make_engine()

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.85)],
        "severity": "HIGH",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.4,
        "similarity_result": _make_similarity_result(0.4),
    }
    reasoning = {
        "model_mode": "hybrid",
        "narrative": "LLM-generated narrative about card testing",
        "confidence": 0.88,
        "risk_assessment": "HIGH",
    }

    result = await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-hyb-1",
        reasoning=reasoning,
    )

    assert result["model_mode"] == "hybrid"


@pytest.mark.asyncio
async def test_generate_hybrid_mode_uses_narrative_as_summary():
    """generate() prefixes deterministic summary and appends LLM narrative."""
    engine = _make_engine()

    captured_kwargs: dict = {}

    async def capture_upsert(**kwargs):
        captured_kwargs.update(kwargs)
        return {"insight_id": "ins-cap", "severity": "HIGH"}

    engine.insight_repo.upsert_insight = capture_upsert

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.7)],
        "severity": "HIGH",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.2,
        "similarity_result": _make_similarity_result(0.2),
    }
    reasoning = {
        "model_mode": "hybrid",
        "narrative": "Unusual burst of transactions at multiple merchants",
        "confidence": 0.9,
    }

    await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-narr-1",
        reasoning=reasoning,
    )

    summary = captured_kwargs["summary"]
    assert "Analyst narrative:" in summary
    assert "Unusual burst of transactions at multiple merchants" in summary
    assert "fraud" in summary.lower() or "risk" in summary.lower()


@pytest.mark.asyncio
async def test_generate_uses_generate_summary_when_no_narrative():
    """generate() falls back to _generate_summary when reasoning has no narrative."""
    engine = _make_engine()

    captured_kwargs: dict = {}

    async def capture_upsert(**kwargs):
        captured_kwargs.update(kwargs)
        return {"insight_id": "ins-gen", "severity": "MEDIUM"}

    engine.insight_repo.upsert_insight = capture_upsert

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.1)],
        "severity": "MEDIUM",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.1,
        "similarity_result": _make_similarity_result(0.1),
    }

    await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-no-narr-1",
        reasoning=None,
    )

    # Should have a non-empty summary from _generate_summary
    assert captured_kwargs["summary"]
    assert isinstance(captured_kwargs["summary"], str)


@pytest.mark.asyncio
async def test_generate_returns_dict_with_required_keys():
    """generate() always returns dict with insight, recommendations, model_mode."""
    engine = _make_engine()

    pattern_analysis = {
        "pattern_scores": [],
        "severity": "LOW",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.0,
        "similarity_result": _make_similarity_result(0.0),
    }

    result = await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-keys-1",
        reasoning=None,
    )

    assert "insight" in result
    assert "recommendations" in result
    assert "model_mode" in result


@pytest.mark.asyncio
async def test_generate_with_reasoning_adds_llm_fields_to_payload():
    """generate() with reasoning adds llm_narrative and llm_confidence to rec payload."""
    engine = _make_engine()

    captured_payloads: list[dict] = []

    async def capture_upsert_rec(**kwargs):
        captured_payloads.append(kwargs.get("payload", {}))
        return {"recommendation_id": "rec-payload", "status": "OPEN"}

    engine.recommendation_repo.upsert_recommendation = capture_upsert_rec

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.95)],
        "severity": "CRITICAL",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.6,
        "similarity_result": _make_similarity_result(0.6),
    }
    reasoning = {
        "model_mode": "hybrid",
        "narrative": "Card testing pattern detected",
        "confidence": 0.92,
        "risk_assessment": "CRITICAL",
    }

    await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-llm-payload",
        reasoning=reasoning,
    )

    assert len(captured_payloads) > 0
    first_payload = captured_payloads[0]
    assert "llm_narrative" in first_payload
    assert first_payload["llm_narrative"] == "Card testing pattern detected"
    assert first_payload["llm_confidence"] == 0.92
    assert first_payload["llm_status"] == "applied"
    assert first_payload["llm_error"] is None


@pytest.mark.asyncio
async def test_generate_without_reasoning_marks_llm_skipped():
    """Deterministic generation should persist explicit LLM status metadata."""
    engine = _make_engine()

    captured_payloads: list[dict] = []

    async def capture_upsert_rec(**kwargs):
        captured_payloads.append(kwargs.get("payload", {}))
        return {"recommendation_id": "rec-det", "status": "OPEN"}

    engine.recommendation_repo.upsert_recommendation = capture_upsert_rec

    await engine.generate(
        context=_make_context(),
        pattern_analysis={
            "pattern_scores": [_make_pattern_score("velocity", 0.1)],
            "severity": "LOW",
        },
        similarity_analysis={"similarity_result": _make_similarity_result(0.1)},
        transaction_id="txn-det-status",
        reasoning=None,
    )

    assert captured_payloads
    payload = captured_payloads[0]
    assert payload["llm_status"] == "skipped"
    assert payload["llm_narrative"] == ""
    assert payload["llm_error"] is None


@pytest.mark.asyncio
async def test_generate_without_reasoning_marks_llm_disabled_when_feature_off():
    """Recommendation payload should mirror disabled LLM feature state."""
    engine = _make_engine()
    engine._settings = MagicMock()
    engine._settings.features.enable_llm_reasoning = False

    captured_payloads: list[dict] = []

    async def capture_upsert_rec(**kwargs):
        captured_payloads.append(kwargs.get("payload", {}))
        return {"recommendation_id": "rec-det-disabled", "status": "OPEN"}

    engine.recommendation_repo.upsert_recommendation = capture_upsert_rec

    await engine.generate(
        context=_make_context(),
        pattern_analysis={
            "pattern_scores": [_make_pattern_score("velocity", 0.1)],
            "severity": "LOW",
        },
        similarity_analysis={"similarity_result": _make_similarity_result(0.1)},
        transaction_id="txn-det-disabled",
        reasoning=None,
    )

    assert captured_payloads
    payload = captured_payloads[0]
    assert payload["llm_status"] == "disabled"
    assert payload["llm_narrative"] == ""
    assert payload["llm_error"] is None


@pytest.mark.asyncio
async def test_generate_with_reasoning_error_marks_fallback():
    """LLM failure payload should be persisted as explicit fallback metadata."""
    engine = _make_engine()

    captured_payloads: list[dict] = []

    async def capture_upsert_rec(**kwargs):
        captured_payloads.append(kwargs.get("payload", {}))
        return {"recommendation_id": "rec-fallback", "status": "OPEN"}

    engine.recommendation_repo.upsert_recommendation = capture_upsert_rec

    await engine.generate(
        context=_make_context(),
        pattern_analysis={
            "pattern_scores": [_make_pattern_score("velocity", 0.9)],
            "severity": "HIGH",
        },
        similarity_analysis={"similarity_result": _make_similarity_result(0.6)},
        transaction_id="txn-llm-error",
        reasoning={
            "model_mode": "deterministic",
            "error": "llm_reasoning_failed",
            "error_detail": "HTTPError: timeout",
        },
    )

    assert captured_payloads
    payload = captured_payloads[0]
    assert payload["llm_status"] == "fallback"
    assert payload["llm_error"] == "HTTPError: timeout"
    assert payload["llm_narrative"] == ""


# ---------------------------------------------------------------------------
# _generate_summary() - severity + pattern_name combinations
# ---------------------------------------------------------------------------


def test_generate_summary_critical_velocity():
    """_generate_summary() for CRITICAL + velocity returns cross-merchant message."""
    engine = _make_engine()
    scores = [_make_pattern_score("velocity", 0.9)]
    summary = engine._generate_summary("CRITICAL", scores)
    assert "burst" in summary.lower() or "velocity" in summary.lower() or "cross" in summary.lower()


def test_generate_summary_critical_decline_anomaly():
    """_generate_summary() for CRITICAL + decline_anomaly returns decline-rate message."""
    engine = _make_engine()
    scores = [_make_pattern_score("decline_anomaly", 0.8)]
    summary = engine._generate_summary("CRITICAL", scores)
    assert "decline" in summary.lower()


def test_generate_summary_critical_other_pattern():
    """_generate_summary() for CRITICAL with other patterns returns severity message."""
    engine = _make_engine()
    scores = [_make_pattern_score("cross_merchant", 0.75)]
    summary = engine._generate_summary("CRITICAL", scores)
    assert "CRITICAL" in summary or "critical" in summary.lower()


def test_generate_summary_high_velocity():
    """_generate_summary() for HIGH + velocity returns cross-merchant message."""
    engine = _make_engine()
    scores = [_make_pattern_score("velocity", 0.85)]
    summary = engine._generate_summary("HIGH", scores)
    assert summary


def test_generate_summary_high_decline_anomaly():
    """_generate_summary() for HIGH + decline_anomaly returns decline message."""
    engine = _make_engine()
    scores = [_make_pattern_score("decline_anomaly", 0.65)]
    summary = engine._generate_summary("HIGH", scores)
    assert "decline" in summary.lower()


def test_generate_summary_medium():
    """_generate_summary() for MEDIUM returns moderate risk message."""
    engine = _make_engine()
    scores = [_make_pattern_score("velocity", 0.4)]
    summary = engine._generate_summary("MEDIUM", scores)
    assert "moderate" in summary.lower() or "medium" in summary.lower()


def test_generate_summary_low():
    """_generate_summary() for LOW returns low-risk message."""
    engine = _make_engine()
    scores = [_make_pattern_score("velocity", 0.1)]
    summary = engine._generate_summary("LOW", scores)
    assert "low" in summary.lower() or "no significant" in summary.lower()


def test_generate_summary_low_with_counter_evidence():
    """_generate_summary() surfaces transaction-context counter-evidence when risk is low."""
    engine = _make_engine()
    summary = engine._generate_summary(
        "LOW",
        [_make_pattern_score("velocity", 0.1)],
        context={"transaction_context": {"3ds_verified": True, "device_trusted": True}},
    )
    assert "counter-evidence" in summary.lower()
    assert "3ds" in summary.lower()
    assert "trusted device" in summary.lower()


def test_counter_evidence_labels_expanded():
    """Expanded counter-evidence labels should be extracted from transaction_context."""
    engine = _make_engine()
    labels = engine._counter_evidence_labels(
        {
            "transaction_context": {
                "3ds_verified": True,
                "device_trusted": True,
                "cardholder_present": True,
                "is_recurring_customer": True,
                "avs_match": True,
                "cvv_match": True,
                "is_tokenized": True,
                "is_known_merchant": True,
            }
        }
    )
    assert "3DS verified" in labels
    assert "trusted device" in labels
    assert "cardholder present" in labels
    assert "recurring customer" in labels
    assert "AVS matched" in labels
    assert "CVV verified" in labels
    assert "tokenized payment" in labels
    assert "known merchant" in labels


def test_counter_evidence_labels_response_codes():
    """AVS and CVV response codes should also be recognized."""
    engine = _make_engine()
    labels = engine._counter_evidence_labels(
        {
            "transaction_context": {
                "avs_response": "Y",
                "cvv_response": "Y",
            }
        }
    )
    assert "AVS matched" in labels
    assert "CVV verified" in labels


def test_counter_evidence_labels_payment_token():
    """Payment token indicator should be recognized."""
    engine = _make_engine()
    labels = engine._counter_evidence_labels(
        {
            "transaction_context": {
                "payment_token_present": True,
            }
        }
    )
    assert "tokenized payment" in labels


def test_counter_evidence_labels_empty_context():
    """Empty transaction_context should return empty list."""
    engine = _make_engine()
    labels = engine._counter_evidence_labels({})
    assert labels == []


def test_counter_evidence_labels_none_context():
    """None context should return empty list."""
    engine = _make_engine()
    labels = engine._counter_evidence_labels(None)
    assert labels == []


def test_generate_summary_empty_pattern_scores():
    """_generate_summary() handles empty pattern scores without error."""
    engine = _make_engine()
    summary = engine._generate_summary("HIGH", [])
    assert isinstance(summary, str)
    assert summary


def test_generate_summary_high_similarity_included():
    """High-severity summaries should mention similarity evidence when it drives risk."""
    engine = _make_engine()
    sim = _make_similarity_result(overall_score=0.91, matches=[{"id": "a"}, {"id": "b"}])
    summary = engine._generate_summary("HIGH", [], similarity_result=sim)
    assert "similarity" in summary.lower()
    assert "0.91" in summary or "0.9" in summary


@pytest.mark.asyncio
async def test_generate_hybrid_conflicting_low_risk_narrative_is_dropped():
    """Conflicting low-risk LLM narrative should not override high deterministic severity."""
    engine = _make_engine()
    captured_kwargs: dict = {}

    async def capture_upsert(**kwargs):
        captured_kwargs.update(kwargs)
        return {"insight_id": "ins-conflict", "severity": "HIGH"}

    engine.insight_repo.upsert_insight = capture_upsert

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.8)],
        "severity": "HIGH",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.6,
        "similarity_result": _make_similarity_result(0.6),
    }
    reasoning = {
        "model_mode": "hybrid",
        "narrative": "This is a low risk transaction with minimal risk indicators.",
        "confidence": 0.9,
    }

    await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-conflict-1",
        reasoning=reasoning,
    )

    summary = captured_kwargs["summary"].lower()
    assert "likely fraud detected" in summary
    assert "analyst narrative:" not in summary


def test_generate_summary_below_threshold_patterns_ignored():
    """_generate_summary() ignores pattern scores <= 0.5 when checking pattern names."""
    engine = _make_engine()
    # velocity score is 0.3 (below 0.5 threshold), so won't appear in patterns list
    scores = [_make_pattern_score("velocity", 0.3)]
    summary = engine._generate_summary("CRITICAL", scores)
    # Should fall through to the generic "High severity" message since velocity score < 0.5
    assert "HIGH" in summary or "CRITICAL" in summary or "fraud" in summary.lower()


# ---------------------------------------------------------------------------
# Multiple recommendation candidates
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_generate_with_multiple_candidates_calls_upsert_rec_multiple_times():
    """generate() calls upsert_recommendation once per recommendation candidate."""
    engine = _make_engine()

    upsert_count = 0

    async def count_upserts(**kwargs):
        nonlocal upsert_count
        upsert_count += 1
        return {"recommendation_id": f"rec-{upsert_count}", "status": "OPEN"}

    engine.recommendation_repo.upsert_recommendation = count_upserts

    # High severity + high velocity + high similarity => multiple candidates
    pattern_analysis = {
        "pattern_scores": [
            _make_pattern_score("velocity", 0.9),
            _make_pattern_score("decline_anomaly", 0.7),
        ],
        "severity": "CRITICAL",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.8,
        "similarity_result": _make_similarity_result(0.8),
    }

    result = await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-multi-1",
        reasoning=None,
    )

    # At least 2 recommendations should be generated for this scenario
    assert len(result["recommendations"]) >= 2
    assert upsert_count >= 2


@pytest.mark.asyncio
async def test_generate_with_no_candidates_produces_standard_review():
    """generate() returns standard review recommendation when no signals detected."""
    engine = _make_engine()

    pattern_analysis = {
        "pattern_scores": [_make_pattern_score("velocity", 0.1)],
        "severity": "LOW",
        "patterns": [],
    }
    similarity_analysis = {
        "overall_score": 0.1,
        "similarity_result": _make_similarity_result(0.1),
    }

    result = await engine.generate(
        context=_make_context(),
        pattern_analysis=pattern_analysis,
        similarity_analysis=similarity_analysis,
        transaction_id="txn-low-1",
        reasoning=None,
    )

    # Should still produce at least one recommendation (the default standard review)
    assert len(result["recommendations"]) >= 1
