"""Recommendation engine - DB-bound module that generates and persists recommendations."""

import logging
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.recommendation_engine_core import (
    compute_insight_severity,
    generate_recommendations,
)
from app.agents.similarity_utils import get_similarity_match_count, get_similarity_score
from app.core.config import get_settings
from app.persistence.insight_repository import InsightRepository
from app.persistence.recommendation_repository import RecommendationRepository
from app.utils.hashing import hash_llm_reasoning
from app.utils.idempotency import compute_insight_key, compute_recommendation_key

log = logging.getLogger(__name__)


class RecommendationEngine:
    """DB-bound recommendation engine."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self._settings = get_settings()
        self.insight_repo = InsightRepository(session)
        self.recommendation_repo = RecommendationRepository(session)

    async def generate(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        transaction_id: str,
        reasoning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Generate insights and recommendations.

        Args:
            context: Transaction context
            pattern_analysis: Pattern analysis results
            similarity_analysis: Similarity analysis results
            transaction_id: Transaction ID
            reasoning: Optional LLM reasoning result for hybrid mode

        Returns:
            Dict with insight and recommendations
        """
        pattern_scores = pattern_analysis.get("pattern_scores") or pattern_analysis.get(
            "patterns", []
        )
        similarity_result = similarity_analysis.get("similarity_result") or {
            "overall_score": similarity_analysis.get("overall_score", 0.0)
        }

        severity = pattern_analysis.get("severity") or compute_insight_severity(
            pattern_scores, similarity_result
        )

        transaction = context.get("transaction")
        tx_timestamp = str(transaction.transaction_timestamp) if transaction else ""

        if reasoning is not None:
            model_mode = reasoning.get("model_mode", "hybrid")
            insight_summary = str(
                reasoning.get("narrative", "") or reasoning.get("insight_summary", "")
            ).strip()
        else:
            model_mode = "deterministic"
            insight_summary = ""

        insight_key = compute_insight_key(
            transaction_id=transaction_id,
            evaluation_type="deterministic",
            transaction_timestamp=tx_timestamp,
            insight_type="fraud_analysis",
            model_mode=model_mode,
        )

        deterministic_summary = self._generate_summary(
            severity,
            pattern_scores,
            similarity_result=similarity_result,
            context=context,
        )
        if insight_summary and self._narrative_conflicts_severity(severity, insight_summary):
            log.warning(
                "Dropping conflicting analyst narrative for severity",
                extra={"severity": severity, "model_mode": model_mode},
            )
            insight_summary = ""

        if insight_summary:
            compact_narrative = " ".join(insight_summary.split())
            summary = f"{deterministic_summary} Analyst narrative: {compact_narrative}"
        else:
            summary = deterministic_summary

        insight = await self.insight_repo.upsert_insight(
            transaction_id=transaction_id,
            severity=severity,
            summary=summary,
            insight_type="fraud_analysis",
            model_mode=model_mode,
            idempotency_key=insight_key,
        )

        candidates = generate_recommendations(
            pattern_scores=pattern_scores,
            similarity_result=similarity_result,
            severity=severity,
            context=context,
        )

        recommendations = []
        for candidate in candidates:
            rec_key = compute_recommendation_key(
                insight_id=insight["insight_id"],
                recommendation_type=candidate.recommendation_type,
                recommendation_signature_hash=candidate.signature_hash,
            )

            payload: dict[str, Any] = {
                "title": candidate.title,
                "impact": candidate.impact,
            }
            payload.update(self._llm_payload_fields(reasoning, model_mode))

            rec = await self.recommendation_repo.upsert_recommendation(
                insight_id=insight["insight_id"],
                recommendation_type=candidate.recommendation_type,
                payload=payload,
                idempotency_key=rec_key,
            )
            recommendations.append(rec)

        return {
            "insight": insight,
            "recommendations": recommendations,
            "model_mode": model_mode,
        }

    def _llm_payload_fields(
        self, reasoning: dict[str, Any] | None, model_mode: str
    ) -> dict[str, Any]:
        """Normalize LLM metadata to make fallback/audit state explicit."""
        default_status = (
            "disabled" if not self._settings.features.enable_llm_reasoning else "skipped"
        )
        payload: dict[str, Any] = {
            "llm_status": default_status,
            "model_mode": model_mode,
            "llm_narrative": "",
            "llm_confidence": None,
            "llm_risk_assessment": None,
            "llm_error": None,
            "llm_model": None,
            "llm_latency_ms": None,
            "llm_reasoning_hash": None,
        }

        if reasoning is None:
            return payload

        error = reasoning.get("error")
        error_detail = reasoning.get("error_detail")
        if error:
            payload["llm_status"] = "fallback"
            payload["llm_error"] = str(error_detail or error)
            return payload

        payload["llm_status"] = "applied" if model_mode == "hybrid" else "deterministic"
        payload["llm_narrative"] = reasoning.get("narrative", "")
        payload["llm_confidence"] = reasoning.get("confidence")
        payload["llm_risk_assessment"] = reasoning.get("risk_assessment")
        payload["llm_model"] = reasoning.get("llm_model")
        payload["llm_latency_ms"] = reasoning.get("llm_latency_ms")
        payload["llm_reasoning_hash"] = RecommendationEngine._reasoning_hash(reasoning)
        return payload

    @staticmethod
    def _reasoning_hash(reasoning: dict[str, Any]) -> str | None:
        """Create stable hash for LLM reasoning payload for audit correlation."""
        return hash_llm_reasoning(reasoning)

    @staticmethod
    def _counter_evidence_labels(context: dict[str, Any] | None) -> list[str]:
        tx_context = (context or {}).get("transaction_context")
        if not isinstance(tx_context, dict):
            return []

        labels: list[str] = []
        if tx_context.get("3ds_verified") is True:
            labels.append("3DS verified")
        if tx_context.get("device_trusted") is True:
            labels.append("trusted device")
        if tx_context.get("cardholder_present") is True:
            labels.append("cardholder present")
        if tx_context.get("is_recurring_customer") is True:
            labels.append("recurring customer")
        if tx_context.get("avs_match") is True or tx_context.get("avs_response") == "Y":
            labels.append("AVS matched")
        if tx_context.get("cvv_match") is True or tx_context.get("cvv_response") == "Y":
            labels.append("CVV verified")
        if (
            tx_context.get("is_tokenized") is True
            or tx_context.get("payment_token_present") is True
        ):
            labels.append("tokenized payment")
        if tx_context.get("is_known_merchant") is True:
            labels.append("known merchant")
        return labels

    @staticmethod
    def _pattern_details(pattern_scores: list[Any]) -> dict[str, dict[str, Any]]:
        details: dict[str, dict[str, Any]] = {}
        for score in pattern_scores:
            if isinstance(score, dict):
                name = str(score.get("pattern_name", ""))
                value = float(score.get("score", 0.0))
                metadata = score.get("details") or {}
            else:
                name = str(getattr(score, "pattern_name", ""))
                value = float(getattr(score, "score", 0.0))
                metadata = getattr(score, "details", {}) or {}
            if not name:
                continue
            details[name] = {
                "score": value,
                "details": metadata if isinstance(metadata, dict) else {},
            }
        return details

    def _generate_summary(
        self,
        severity: str,
        pattern_scores: list[Any],
        similarity_result: Any = None,
        context: dict[str, Any] | None = None,
    ) -> str:
        """Generate detailed deterministic insight summary from scored evidence.

        Produces a multi-sentence analyst-quality narrative with transaction
        context, pattern breakdown, counter-evidence, and data quality flags.
        """
        details = self._pattern_details(pattern_scores)

        velocity = details.get("velocity", {})
        velocity_score = float(velocity.get("score", 0.0))
        velocity_burst_1h = (velocity.get("details") or {}).get("burst_1h")

        decline = details.get("decline_anomaly", {})
        decline_score = float(decline.get("score", 0.0))
        decline_ratio = (decline.get("details") or {}).get("decline_ratio_24h")

        cross = details.get("cross_merchant", {})
        cross_score = float(cross.get("score", 0.0))
        unique_merchants = (cross.get("details") or {}).get("unique_merchants_24h")

        amount_info = details.get("amount_anomaly", {})
        amount_score = float(amount_info.get("score", 0.0))
        amount_details = amount_info.get("details") or {}

        time_info = details.get("time_anomaly", {})
        time_score = float(time_info.get("score", 0.0))
        time_details = time_info.get("details") or {}

        indicators: list[str] = []

        if velocity_score >= 0.5:
            if velocity_burst_1h is not None:
                indicators.append(f"velocity burst ({velocity_burst_1h} transactions in 1h)")
            else:
                indicators.append("velocity anomaly")

        if decline_score >= 0.5:
            if isinstance(decline_ratio, int | float):
                indicators.append(f"high decline ratio ({decline_ratio * 100:.0f}% in 24h)")
            else:
                indicators.append("high decline ratio")

        if cross_score >= 0.5:
            if unique_merchants is not None:
                indicators.append(
                    f"cross-merchant spread ({unique_merchants} unique merchants in 24h)"
                )
            else:
                indicators.append("cross-merchant spread")

        if amount_score >= 0.3:
            amount_parts: list[str] = []
            if amount_details.get("round_number"):
                amount_parts.append(f"round number (${amount_details.get('amount', '?')})")
            if amount_details.get("high_amount"):
                amount_parts.append(f"high amount (${amount_details.get('high_amount')})")
            if amount_details.get("elevated_amount"):
                amount_parts.append(f"elevated (${amount_details.get('elevated_amount')})")
            if amount_details.get("outlier"):
                z = amount_details.get("z_score", "?")
                amount_parts.append(f"statistical outlier (z-score: {z})")
            if amount_details.get("spike_vs_avg"):
                amount_parts.append(f"{amount_details['spike_vs_avg']}x spike vs average")
            if amount_parts:
                indicators.append(f"amount anomaly: {', '.join(amount_parts)}")

        if time_score >= 0.3:
            time_parts: list[str] = []
            if time_details.get("unusual_hour") is not None:
                time_parts.append(f"unusual hour ({time_details['unusual_hour']}:00)")
            if time_details.get("timezone_mismatch"):
                ip_c = time_details.get("ip_country", "?")
                card_c = time_details.get("card_country", "?")
                time_parts.append(f"timezone mismatch ({ip_c} vs {card_c})")
            if time_details.get("high_risk_combo"):
                time_parts.append("high-risk merchant + unusual hour")
            if time_parts:
                indicators.append(f"time anomaly: {', '.join(time_parts)}")

        similarity_score = self._similarity_overall(similarity_result)
        if similarity_score >= 0.6:
            similarity_matches = self._similarity_match_count(similarity_result)
            if similarity_matches > 0:
                indicators.append(
                    f"high similarity to {similarity_matches} prior transactions "
                    f"(score {similarity_score:.2f})"
                )
            else:
                indicators.append(f"high similarity score ({similarity_score:.2f})")

        card_testing = velocity_score >= 0.5 and decline_score >= 0.5 and cross_score >= 0.5
        if card_testing:
            indicators.insert(0, "card testing pattern")

        parts: list[str] = []

        # --- Lead sentence: severity and primary finding ---
        if severity in ("CRITICAL", "HIGH"):
            if indicators:
                parts.append(f"Likely fraud detected ({severity}): {', '.join(indicators)}.")
            else:
                parts.append(
                    f"Likely fraud detected ({severity}): strong anomaly score "
                    f"with limited pattern detail."
                )
        elif severity == "MEDIUM":
            if indicators:
                parts.append(f"Moderate fraud risk indicators present: {', '.join(indicators)}.")
            else:
                parts.append("Moderate fraud risk indicators present.")
        else:
            counter_evidence = self._counter_evidence_labels(context)
            if counter_evidence:
                parts.append(
                    "Low fraud risk: counter-evidence observed "
                    f"({', '.join(counter_evidence)}), recommendation downgraded and routed for analyst review."
                )
            elif indicators:
                parts.append(
                    "Low fraud risk at present, but suspicious signals were flagged "
                    f"({', '.join(indicators)}). Keep in analyst review queue."
                )
            else:
                parts.append(
                    "Low fraud risk - no anomalies detected. Routine analyst review can close quickly."
                )

        # --- Transaction context line ---
        tx_line = self._build_transaction_context_line(context)
        if tx_line:
            parts.append(tx_line)

        # --- Card history line ---
        card_line = self._build_card_history_line(context)
        if card_line:
            parts.append(card_line)

        # --- Data quality flags ---
        missing_flags = self._build_data_quality_flags(context)
        if missing_flags:
            parts.append(f"Data gaps: {', '.join(missing_flags)}.")

        return " ".join(parts)

    @staticmethod
    def _build_transaction_context_line(context: dict[str, Any] | None) -> str:
        """Build a concise transaction context description."""
        if not context:
            return ""
        transaction = context.get("transaction")
        if not transaction:
            return ""
        amount = getattr(transaction, "amount", None)
        if amount is None and isinstance(transaction, dict):
            amount = transaction.get("amount")
        currency = (
            getattr(transaction, "currency", None)
            or (transaction.get("currency") if isinstance(transaction, dict) else None)
            or "USD"
        )
        merchant_id = (
            getattr(transaction, "merchant_id", None)
            or (transaction.get("merchant_id") if isinstance(transaction, dict) else None)
            or "unknown"
        )
        status = (
            getattr(transaction, "status", None)
            or (transaction.get("status") if isinstance(transaction, dict) else None)
            or "unknown"
        )
        tx_context = context.get("transaction_context") or {}
        mcc = (
            getattr(transaction, "merchant_category", None)
            or (transaction.get("merchant_category") if isinstance(transaction, dict) else None)
            or tx_context.get("merchant_category_code")
            or "unknown"
        )
        if amount is not None:
            return (
                f"Transaction: ${float(amount):.2f} {currency} at {merchant_id} "
                f"(MCC: {mcc}), decision: {status}."
            )
        return ""

    @staticmethod
    def _build_card_history_line(context: dict[str, Any] | None) -> str:
        """Build card history context description."""
        if not context:
            return ""
        velocity = context.get("velocity_snapshot") or {}
        if isinstance(velocity, dict):
            tx_count = velocity.get("transaction_count_90d")
            approval_rate = velocity.get("approval_rate_90d")
            v24h = velocity.get("velocity_24h")
            parts: list[str] = []
            if tx_count is not None:
                parts.append(f"{tx_count} transactions (90d)")
            if approval_rate is not None:
                try:
                    parts.append(f"{float(approval_rate):.0%} approval rate")
                except ValueError, TypeError:
                    pass
            if v24h is not None:
                parts.append(f"{v24h} in last 24h")
            if parts:
                return f"Card history: {', '.join(parts)}."
        card_history = context.get("card_history") or []
        if card_history:
            return f"Card history: {len(card_history)} recent transactions on file."
        return ""

    @staticmethod
    def _build_data_quality_flags(context: dict[str, Any] | None) -> list[str]:
        """Identify missing data that limits analysis confidence."""
        if not context:
            return ["no context available"]
        flags: list[str] = []
        tx_context = context.get("transaction_context") or {}
        velocity = context.get("velocity_snapshot") or {}
        if not velocity or (isinstance(velocity, dict) and not velocity):
            flags.append("no velocity history")
        if "3ds_verified" not in tx_context and "three_ds_authenticated" not in tx_context:
            flags.append("3DS status unknown")
        if "device_trusted" not in tx_context:
            flags.append("device trust unknown")
        if "avs_match" not in tx_context and "avs_response" not in tx_context:
            flags.append("AVS not checked")
        if "cvv_match" not in tx_context and "cvv_response" not in tx_context:
            flags.append("CVV not checked")
        card_history = context.get("card_history") or []
        if not card_history:
            flags.append("no card history available")
        return flags

    @staticmethod
    def _similarity_overall(similarity_result: Any) -> float:
        return get_similarity_score(similarity_result)

    @staticmethod
    def _similarity_match_count(similarity_result: Any) -> int:
        return get_similarity_match_count(similarity_result)

    @staticmethod
    def _narrative_conflicts_severity(severity: str, narrative: str) -> bool:
        text = " ".join(narrative.lower().split())
        if not text:
            return False

        low_risk_markers = (
            "low risk",
            "minimal risk",
            "benign",
            "no detected patterns",
            "no similar transactions",
        )
        high_risk_markers = (
            "high risk",
            "critical risk",
            "likely fraud",
            "card testing",
            "velocity burst",
            "decline anomaly",
        )

        if severity in {"HIGH", "CRITICAL"}:
            return any(marker in text for marker in low_risk_markers)
        if severity == "LOW":
            return any(marker in text for marker in high_risk_markers)
        return False
