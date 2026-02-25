"""Core logic for investigation tools - preserved from original *_core.py files."""

from app.tools._core.context_logic import (
    Signal,
    TransactionContext,
    WindowStats,
    assemble_context,
    compute_all_windows,
    compute_window_stats,
    extract_signals,
)
from app.tools._core.pattern_logic import (
    PatternScore,
    compute_severity,
    run_pattern_scoring,
    score_amount_anomalies,
    score_card_testing,
    score_cross_merchant_patterns,
    score_decline_anomalies,
    score_time_anomalies,
    score_velocity_patterns,
)
from app.tools._core.reasoning_logic import (
    assemble_prompt_payload,
    parse_llm_response,
)
from app.tools._core.recommendation_logic import (
    RecommendationCandidate,
    generate_recommendations,
)
from app.tools._core.rule_draft_logic import (
    RuleCondition,
    RuleDraftPayload,
    assemble_draft_payload,
    validate_draft_payload,
)
from app.tools._core.similarity_logic import (
    SimilarityMatch,
    SimilarityResult,
    evaluate_similarity,
    freshness_weight,
)

__all__ = [
    "TransactionContext",
    "WindowStats",
    "Signal",
    "compute_window_stats",
    "compute_all_windows",
    "extract_signals",
    "assemble_context",
    "PatternScore",
    "score_amount_anomalies",
    "score_time_anomalies",
    "score_velocity_patterns",
    "score_decline_anomalies",
    "score_cross_merchant_patterns",
    "score_card_testing",
    "run_pattern_scoring",
    "compute_severity",
    "SimilarityMatch",
    "SimilarityResult",
    "freshness_weight",
    "evaluate_similarity",
    "RecommendationCandidate",
    "generate_recommendations",
    "assemble_prompt_payload",
    "parse_llm_response",
    "RuleCondition",
    "RuleDraftPayload",
    "assemble_draft_payload",
    "validate_draft_payload",
]
