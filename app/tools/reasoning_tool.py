"""Reasoning tool - LLM-powered fraud reasoning based on collected evidence."""

from __future__ import annotations

import json
import re
import time
from typing import TYPE_CHECKING, Any

import structlog
from langchain_core.messages import HumanMessage, SystemMessage
from opentelemetry import trace

from app.agent.state import update_state
from app.core.metrics import (
    ops_agent_llm_calls_total,
    ops_agent_llm_latency_seconds,
    ops_agent_llm_tokens_total,
)
from app.tools._core.reasoning_logic import (
    assemble_prompt_payload,
    parse_llm_response,
    validate_prompt_payload,
)
from app.tools.base import BaseTool
from app.utils.redaction import redact_state_for_llm

if TYPE_CHECKING:
    from langchain_core.language_models import BaseChatModel

    from app.agent.state import InvestigationState

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)

REASONING_SYSTEM_PROMPT = """You are a fraud investigation reasoning engine.
Analyze the provided evidence and generate a structured risk assessment.

You must respond with a JSON object containing:
{
  "narrative": "<concise explanation of findings>",
  "risk_level": "CRITICAL|HIGH|MEDIUM|LOW",
  "key_findings": ["<finding 1>", "<finding 2>", ...],
  "hypotheses": [
    {
      "hypothesis": "<hypothesis description>",
      "confidence": <0.0-1.0>,
      "supporting_evidence": ["<evidence ref 1>", ...],
      "contradicting_evidence": ["<evidence ref 1>", ...]
    },
    ...
  ],
  "known_facts": ["<fact 1 from context.features>", ...],
  "unknowns": ["<explicitly unknown item 1>", ...],
  "what_would_change_mind": ["<evidence that would change assessment>", ...],
  "confidence": <0.0-1.0>,
  "evidence_citations": ["<citation to tool output>", ...]
}

Response formatting requirements:
- Return RAW JSON only (no markdown, no code fences, no commentary).
- Keep narrative concise (max 320 characters).
- Keep key_findings to at most 5 short items.
- Keep 2-4 hypotheses with individual confidence scores.
- Known facts must reference specific fields from context.features (e.g., "txn_count_1h=6", "amount_zscore=2.3").
- Each hypothesis must cite supporting and contradicting evidence by referencing tool outputs.
- Explicitly list unknowns when evidence is missing.
- List what evidence would change your mind in "what_would_change_mind".

If evidence is insufficient, explicitly state that in narrative/key_findings and populate "unknowns".
Do not speculate beyond the provided data.
"""

REASONING_MIN_MAX_TOKENS = 1024
LOW_RISK_LANGUAGE_MARKERS = (
    "no patterns detected",
    "no detected patterns",
    "no patterns",
    "no similar transactions found",
    "no similar transactions",
    "low risk",
    "routine",
    "typical usage",
    "appears routine",
)


class ReasoningTool(BaseTool):
    """Perform LLM-powered fraud reasoning based on collected evidence."""

    @property
    def name(self) -> str:
        return "reasoning_tool"

    @property
    def description(self) -> str:
        return "Perform LLM-powered fraud reasoning based on collected evidence to generate risk assessment and hypotheses"

    def __init__(self, llm: BaseChatModel, settings: Any = None) -> None:
        self._llm = llm
        self._settings = settings

    async def execute(self, state: InvestigationState) -> InvestigationState:
        from app.core.config import get_settings

        settings = self._settings or get_settings()
        prompt_guard_enabled = settings.llm.prompt_guard_enabled

        with tracer.start_as_current_span("tool.reasoning") as span:
            span.set_attribute("investigation_id", state["investigation_id"])
            span.set_attribute("tool_name", self.name)

            context = state["context"]
            pattern_results = state["pattern_results"]
            similarity_results = state["similarity_results"]

            redacted_context = redact_state_for_llm(context)
            prompt_payload = assemble_prompt_payload(
                context=redacted_context,
                pattern_analysis=pattern_results,
                similarity_analysis=similarity_results,
            )

            if prompt_guard_enabled:
                validation_errors = validate_prompt_payload(prompt_payload)
                if validation_errors:
                    logger.warning(
                        "Prompt guard validation failed",
                        investigation_id=state["investigation_id"],
                        errors=validation_errors[:5],
                        error_count=len(validation_errors),
                    )
                    span.set_attribute("prompt_guard_blocked", True)
                    span.set_attribute("prompt_guard_errors", len(validation_errors))
                    ops_agent_llm_calls_total.labels(
                        purpose="reasoning", status="blocked_by_guard"
                    ).inc()
                    reasoning = self._reasoning_unavailable(
                        state,
                        status="blocked_by_guard",
                        error_detail=f"Prompt guard blocked: {'; '.join(validation_errors[:3])}",
                        prompt_guard_errors=validation_errors[:5],
                    )
                    return self._apply_unavailable_reasoning(state, reasoning)

            messages = [
                SystemMessage(content=REASONING_SYSTEM_PROMPT),
                HumanMessage(content=json.dumps(prompt_payload, default=str)),
            ]

            span.add_event(
                "llm.request",
                {
                    "purpose": "reasoning",
                    "system_prompt_chars": len(REASONING_SYSTEM_PROMPT),
                    "prompt_payload_keys": list(prompt_payload.keys()),
                },
            )

            start_time = time.perf_counter()
            try:
                response = await self._llm.ainvoke(
                    messages,
                    max_tokens=max(settings.llm.max_completion_tokens, REASONING_MIN_MAX_TOKENS),
                )
            except Exception as exc:
                elapsed = time.perf_counter() - start_time
                ops_agent_llm_latency_seconds.labels(purpose="reasoning").observe(elapsed)
                ops_agent_llm_calls_total.labels(purpose="reasoning", status="error").inc()
                span.set_attribute("error", str(exc))
                logger.error(
                    "Reasoning tool LLM call failed",
                    investigation_id=state["investigation_id"],
                    error=str(exc),
                )
                reasoning = self._reasoning_unavailable(
                    state,
                    status="error",
                    error_detail=f"{type(exc).__name__}: {exc}",
                )
                return self._apply_unavailable_reasoning(state, reasoning)

            elapsed = time.perf_counter() - start_time
            ops_agent_llm_latency_seconds.labels(purpose="reasoning").observe(elapsed)

            input_tokens = 0
            output_tokens = 0
            if hasattr(response, "usage_metadata") and response.usage_metadata:
                metadata = response.usage_metadata
                model_name = getattr(self._llm, "model", "unknown")
                if "input_tokens" in metadata:
                    input_tokens = metadata["input_tokens"]
                    ops_agent_llm_tokens_total.labels(model=model_name, type="input").inc(
                        input_tokens
                    )
                if "output_tokens" in metadata:
                    output_tokens = metadata["output_tokens"]
                    ops_agent_llm_tokens_total.labels(model=model_name, type="output").inc(
                        output_tokens
                    )

            response_content = str(response.content)
            span.add_event(
                "llm.response",
                {
                    "purpose": "reasoning",
                    "content_length": len(response_content),
                    "input_tokens": input_tokens,
                    "output_tokens": output_tokens,
                },
            )

            try:
                reasoning = parse_llm_response(response_content)
            except ValueError as exc:
                ops_agent_llm_calls_total.labels(purpose="reasoning", status="parse_error").inc()
                logger.warning(
                    "Reasoning tool returned non-parseable payload",
                    investigation_id=state["investigation_id"],
                    error=str(exc),
                    response_length=len(str(response.content)),
                )
                reasoning = self._reasoning_unavailable(
                    state,
                    status="parse_error",
                    error_detail=str(exc),
                )
                return self._apply_unavailable_reasoning(state, reasoning)

            if "summary" not in reasoning and isinstance(reasoning.get("narrative"), str):
                narrative = reasoning["narrative"].strip()
                if narrative:
                    reasoning["summary"] = narrative
            llm_status = "partial_parse" if bool(reasoning.get("_partial_parse")) else "success"
            ops_agent_llm_calls_total.labels(purpose="reasoning", status=llm_status).inc()
            reasoning["llm_status"] = llm_status

            hypotheses = reasoning.get("hypotheses", [])
            severity = reasoning.get("risk_level", state["severity"])
            if severity not in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                severity = state["severity"]
            calibrated_severity = self._calibrate_llm_severity(state, severity)
            if calibrated_severity != severity:
                reasoning["llm_risk_level"] = severity
                reasoning["severity_calibration"] = "counter_evidence_no_pattern_cap"
                severity = calibrated_severity
                reasoning["risk_level"] = calibrated_severity
            confidence = reasoning.get("confidence", state["confidence_score"])
            reasoning["severity"] = severity
            reasoning = self._harmonize_reasoning_text(state, reasoning, severity)

            span.set_attribute("severity", str(severity))
            span.set_attribute("confidence", float(confidence))

            logger.info(
                "Reasoning tool completed",
                investigation_id=state["investigation_id"],
                severity=severity,
                confidence=confidence,
                findings_count=len(reasoning.get("key_findings", [])),
            )

            return update_state(
                state,
                reasoning=reasoning,
                hypotheses=[*state["hypotheses"], *hypotheses],
                severity=severity,
                confidence_score=float(confidence),
            )

    @classmethod
    def _apply_unavailable_reasoning(
        cls,
        state: InvestigationState,
        reasoning: dict[str, object],
    ) -> InvestigationState:
        severity = cls._max_severity(
            cls._normalize_severity(state.get("severity"), default="LOW"),
            cls._normalize_severity(reasoning.get("severity"), default="LOW"),
        )
        try:
            current_conf = float(state.get("confidence_score", 0.0) or 0.0)
        except TypeError, ValueError:
            current_conf = 0.0
        try:
            fallback_conf = float(reasoning.get("confidence", 0.0) or 0.0)
        except TypeError, ValueError:
            fallback_conf = 0.0
        return update_state(
            state,
            reasoning=reasoning,
            severity=severity,
            confidence_score=max(current_conf, fallback_conf),
        )

    @staticmethod
    def _normalize_severity(value: object, *, default: str) -> str:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in {"LOW", "MEDIUM", "HIGH", "CRITICAL"}:
                return normalized
        return default

    @staticmethod
    def _max_severity(left: str, right: str) -> str:
        rank = {"LOW": 1, "MEDIUM": 2, "HIGH": 3, "CRITICAL": 4}
        return left if rank.get(left, 0) >= rank.get(right, 0) else right

    @staticmethod
    def _pattern_rows(state: InvestigationState) -> list[dict[str, Any]]:
        pattern_results = state.get("pattern_results") if isinstance(state, dict) else {}
        if not isinstance(pattern_results, dict):
            return []
        rows = pattern_results.get("scores")
        if not isinstance(rows, list):
            return []
        return [row for row in rows if isinstance(row, dict)]

    @staticmethod
    def _truthy(value: Any) -> bool:
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return value != 0
        if isinstance(value, str):
            return value.strip().lower() in {"true", "t", "1", "yes", "y"}
        return False

    @staticmethod
    def _value_from_mapping_or_obj(payload: Any, key: str) -> Any:
        if isinstance(payload, dict):
            return payload.get(key)
        return getattr(payload, key, None)

    @classmethod
    def _counter_evidence_count(cls, state: InvestigationState) -> int:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        context_dict = context if isinstance(context, dict) else {}
        tx_context = context_dict.get("transaction_context", {})
        tx_context_dict = tx_context if isinstance(tx_context, dict) else {}
        transaction = context_dict.get("transaction", {})

        features = {
            "three_ds": (
                tx_context_dict.get("3ds_verified"),
                cls._value_from_mapping_or_obj(transaction, "three_ds_authenticated"),
            ),
            "trusted_device": (
                tx_context_dict.get("trusted_device"),
                cls._value_from_mapping_or_obj(transaction, "device_trusted"),
                cls._value_from_mapping_or_obj(transaction, "is_trusted_device"),
            ),
            "cardholder_present": (
                tx_context_dict.get("cardholder_present"),
                cls._value_from_mapping_or_obj(transaction, "cardholder_present"),
            ),
            "recurring_customer": (
                tx_context_dict.get("is_recurring_customer"),
                cls._value_from_mapping_or_obj(transaction, "is_recurring_customer"),
            ),
            "known_merchant": (
                tx_context_dict.get("known_merchant"),
                cls._value_from_mapping_or_obj(transaction, "is_known_merchant"),
            ),
            "avs_match": (
                tx_context_dict.get("avs_match"),
                cls._value_from_mapping_or_obj(transaction, "avs_match"),
            ),
            "cvv_match": (
                tx_context_dict.get("cvv_match"),
                cls._value_from_mapping_or_obj(transaction, "cvv_match"),
            ),
            "tokenized": (
                tx_context_dict.get("tokenized"),
                tx_context_dict.get("payment_token_present"),
                cls._value_from_mapping_or_obj(transaction, "is_tokenized"),
                cls._value_from_mapping_or_obj(transaction, "payment_token_present"),
            ),
        }

        return sum(1 for values in features.values() if any(cls._truthy(v) for v in values))

    @classmethod
    def _max_pattern_score(cls, state: InvestigationState) -> float:
        max_score = 0.0
        for row in cls._pattern_rows(state):
            try:
                score = float(row.get("score", 0.0) or 0.0)
            except TypeError, ValueError:
                score = 0.0
            max_score = max(max_score, score)
        return max_score

    @classmethod
    def _similarity_summary(cls, state: InvestigationState) -> tuple[float, int]:
        similarity = state.get("similarity_results", {}) if isinstance(state, dict) else {}
        similarity_dict = similarity if isinstance(similarity, dict) else {}
        try:
            overall_score = float(similarity_dict.get("overall_score", 0.0) or 0.0)
        except TypeError, ValueError:
            overall_score = 0.0
        matches = similarity_dict.get("matches", [])
        match_count = len(matches) if isinstance(matches, list) else 0
        return overall_score, match_count

    @classmethod
    def _similarity_has_counter_evidence(cls, state: InvestigationState) -> bool:
        similarity = state.get("similarity_results", {}) if isinstance(state, dict) else {}
        similarity_dict = similarity if isinstance(similarity, dict) else {}
        root_counter = similarity_dict.get("counter_evidence")
        if isinstance(root_counter, (list, dict)) and bool(root_counter):
            return True
        matches = similarity_dict.get("matches", [])
        if not isinstance(matches, list):
            return False
        for match in matches:
            counter = cls._value_from_mapping_or_obj(match, "counter_evidence")
            if isinstance(counter, (list, dict)) and bool(counter):
                return True
        return False

    @classmethod
    def _decision(cls, state: InvestigationState) -> str:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        context_dict = context if isinstance(context, dict) else {}
        transaction = context_dict.get("transaction", {})
        decision = cls._value_from_mapping_or_obj(
            transaction, "decision"
        ) or cls._value_from_mapping_or_obj(transaction, "status")
        if isinstance(decision, str):
            return decision.strip().upper()
        return ""

    @classmethod
    def _calibrate_llm_severity(cls, state: InvestigationState, severity: Any) -> str:
        normalized = cls._normalize_severity(severity, default="LOW")

        max_pattern_score = cls._max_pattern_score(state)
        similarity_score, similarity_match_count = cls._similarity_summary(state)
        similarity_has_counter_evidence = cls._similarity_has_counter_evidence(state)
        counter_evidence_count = cls._counter_evidence_count(state)
        score_by_name: dict[str, float] = {}
        for row in cls._pattern_rows(state):
            name = row.get("pattern_name")
            if not isinstance(name, str):
                continue
            try:
                score_by_name[name] = float(row.get("score", 0.0) or 0.0)
            except TypeError, ValueError:
                score_by_name[name] = 0.0
        critical_pattern_score = max(
            score_by_name.get("velocity", 0.0),
            score_by_name.get("decline_anomaly", 0.0),
            score_by_name.get("card_testing", 0.0),
        )
        context = state.get("context", {}) if isinstance(state, dict) else {}
        context_dict = context if isinstance(context, dict) else {}
        rule_matches = context_dict.get("rule_matches", [])
        rule_match_count = len(rule_matches) if isinstance(rule_matches, list) else 0
        decision = cls._decision(state)

        has_strong_counter_evidence = (
            max_pattern_score <= 0.60
            and critical_pattern_score <= 0.55
            and similarity_score <= 0.7
            and similarity_match_count <= 10
            and rule_match_count <= 1
            and (
                counter_evidence_count >= 3
                or (similarity_has_counter_evidence and decision in {"APPROVE", "APPROVED"})
            )
        )

        if normalized in {"MEDIUM", "HIGH"} and has_strong_counter_evidence:
            return "LOW"

        # Guardrail: prevent LOW classification when multiple high-risk patterns align.
        has_high_risk_pattern_combo = score_by_name.get("decline_anomaly", 0.0) >= 0.85 and (
            score_by_name.get("velocity", 0.0) >= 0.65
            or score_by_name.get("card_testing", 0.0) >= 0.65
        )
        if (
            normalized == "LOW"
            and has_high_risk_pattern_combo
            and (similarity_score >= 0.3 or rule_match_count >= 1)
        ):
            return "MEDIUM"

        # Keep a minimum severity when transaction was declined and one strong fraud pattern exists.
        if (
            normalized == "LOW"
            and decision in {"DECLINE", "DECLINED"}
            and max_pattern_score >= 0.75
            and (rule_match_count >= 1 or similarity_score >= 0.5)
        ):
            return "MEDIUM"

        return normalized

    @classmethod
    def _rewrite_low_risk_language(cls, text: str, state: InvestigationState) -> str:
        if not text:
            return text
        max_pattern_score = cls._max_pattern_score(state)
        similarity_score, similarity_match_count = cls._similarity_summary(state)
        rewritten = text
        if max_pattern_score >= 0.5:
            rewritten = re.sub(
                r"no patterns detected|no detected patterns|no patterns",
                "patterns detected with mixed strength",
                rewritten,
                flags=re.IGNORECASE,
            )
        if similarity_match_count > 0 or similarity_score > 0.0:
            rewritten = re.sub(
                r"no similar transactions found|no similar transactions",
                "similar transactions were reviewed",
                rewritten,
                flags=re.IGNORECASE,
            )
        rewritten = re.sub(
            r"\blow risk\b", "elevated risk requires review", rewritten, flags=re.IGNORECASE
        )
        rewritten = re.sub(r"\broutine\b", "requires review", rewritten, flags=re.IGNORECASE)
        rewritten = re.sub(
            r"\btypical usage\b", "activity requires review", rewritten, flags=re.IGNORECASE
        )
        rewritten = re.sub(
            r"\bappears routine\b", "requires analyst review", rewritten, flags=re.IGNORECASE
        )
        return rewritten

    @classmethod
    def _harmonize_reasoning_text(
        cls,
        state: InvestigationState,
        reasoning: dict[str, Any],
        severity: str,
    ) -> dict[str, Any]:
        if severity not in {"MEDIUM", "HIGH", "CRITICAL"}:
            return reasoning
        output = dict(reasoning)
        for key in ("summary", "narrative"):
            value = output.get(key)
            if not isinstance(value, str) or not value:
                continue
            normalized = value.lower()
            if any(marker in normalized for marker in LOW_RISK_LANGUAGE_MARKERS):
                output[key] = cls._rewrite_low_risk_language(value, state)
        return output

    @classmethod
    def _derive_fallback_severity(cls, state: InvestigationState) -> str:
        base = cls._normalize_severity(state.get("severity"), default="LOW")
        score_by_name: dict[str, float] = {}
        for row in cls._pattern_rows(state):
            name = row.get("pattern_name")
            if not isinstance(name, str):
                continue
            try:
                score_by_name[name] = float(row.get("score", 0.0) or 0.0)
            except TypeError, ValueError:
                score_by_name[name] = 0.0

        velocity = score_by_name.get("velocity", 0.0)
        decline = score_by_name.get("decline_anomaly", 0.0)
        card_testing = score_by_name.get("card_testing", 0.0)
        medium_signal_count = sum(1 for score in score_by_name.values() if score >= 0.5)

        context = state.get("context", {}) if isinstance(state, dict) else {}
        context_dict = context if isinstance(context, dict) else {}
        signals = context_dict.get("signals", [])
        signal_names: set[str] = set()
        if isinstance(signals, list):
            for signal in signals:
                name = (
                    signal.get("name")
                    if isinstance(signal, dict)
                    else getattr(signal, "name", None)
                )
                if isinstance(name, str) and name:
                    signal_names.add(name)

        has_decline_signal = "decline_reason" in signal_names
        has_rule_match_signal = "has_rule_matches" in signal_names

        derived = base
        if velocity >= 0.9 and (decline >= 0.5 or has_decline_signal or has_rule_match_signal):
            derived = cls._max_severity(derived, "HIGH")
        elif velocity >= 0.7 and (has_decline_signal or has_rule_match_signal):
            derived = cls._max_severity(derived, "MEDIUM")
        elif decline >= 0.7 and (velocity >= 0.5 or card_testing >= 0.5):
            derived = cls._max_severity(derived, "HIGH")
        elif medium_signal_count >= 2:
            derived = cls._max_severity(derived, "MEDIUM")

        return derived

    @classmethod
    def _fallback_findings(cls, state: InvestigationState) -> list[str]:
        findings = ["Evidence-based fallback synthesis applied."]
        for row in cls._pattern_rows(state):
            name = str(row.get("pattern_name") or "")
            if not name:
                continue
            try:
                score = float(row.get("score", 0.0) or 0.0)
            except TypeError, ValueError:
                continue
            if score < 0.5:
                continue
            details = row.get("details")
            detail_text = ""
            if isinstance(details, dict):
                if name == "velocity" and "burst_1h" in details:
                    detail_text = f"burst_1h={details.get('burst_1h')}"
                elif name == "decline_anomaly" and "decline_ratio_24h" in details:
                    detail_text = f"decline_ratio_24h={details.get('decline_ratio_24h')}"
                elif name == "cross_merchant" and "unique_merchants_24h" in details:
                    detail_text = f"unique_merchants_24h={details.get('unique_merchants_24h')}"
            if detail_text:
                findings.append(f"{name} score {score:.2f} ({detail_text})")
            else:
                findings.append(f"{name} score {score:.2f}")
        return findings[:6]

    @classmethod
    def _fallback_confidence(cls, state: InvestigationState, severity: str) -> float:
        max_score = 0.0
        for row in cls._pattern_rows(state):
            try:
                score = float(row.get("score", 0.0) or 0.0)
            except TypeError, ValueError:
                score = 0.0
            max_score = max(max_score, score)
        if severity in {"HIGH", "CRITICAL"}:
            return round(max(max_score, 0.7), 3)
        if severity == "MEDIUM":
            return round(max(max_score, 0.5), 3)
        if max_score > 0:
            return round(min(max_score, 0.35), 3)
        return 0.1

    @classmethod
    def _reasoning_unavailable(
        cls,
        state: InvestigationState,
        *,
        status: str,
        error_detail: str,
        prompt_guard_errors: list[str] | None = None,
    ) -> dict[str, object]:
        severity = cls._derive_fallback_severity(state)
        findings = cls._fallback_findings(state)
        confidence = cls._fallback_confidence(state, severity)
        summary_facts = (
            "; ".join(findings[1:3]) if len(findings) > 1 else "limited risk signals observed"
        )
        payload: dict[str, object] = {
            "narrative": (
                "Evidence-based fallback synthesis applied because model output was not "
                "usable for strict JSON extraction."
            ),
            "summary": f"Evidence fallback ({severity}): {summary_facts}",
            "risk_level": severity,
            "severity": severity,
            "key_findings": findings,
            "hypotheses": [],
            "confidence": confidence,
            "llm_status": status,
            "error_detail": error_detail[:240],
        }
        if prompt_guard_errors:
            payload["prompt_guard_errors"] = prompt_guard_errors
        return payload
