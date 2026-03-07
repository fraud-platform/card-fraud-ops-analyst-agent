"""Reasoning tool - LLM-powered fraud reasoning based on collected evidence."""

from __future__ import annotations

import asyncio
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
from app.utils.constants import SEVERITY_RANK, VALID_SEVERITIES
from app.utils.data_access import get_attr
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

REASONING_RESPONSE_FORMAT = {
    "type": "object",
    "properties": {
        "narrative": {"type": "string"},
        "risk_level": {
            "type": "string",
            "enum": ["CRITICAL", "HIGH", "MEDIUM", "LOW"],
        },
        "key_findings": {"type": "array", "items": {"type": "string"}},
        "hypotheses": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "hypothesis": {"type": "string"},
                    "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                    "supporting_evidence": {"type": "array", "items": {"type": "string"}},
                    "contradicting_evidence": {"type": "array", "items": {"type": "string"}},
                },
                "required": [
                    "hypothesis",
                    "confidence",
                    "supporting_evidence",
                    "contradicting_evidence",
                ],
            },
        },
        "known_facts": {"type": "array", "items": {"type": "string"}},
        "unknowns": {"type": "array", "items": {"type": "string"}},
        "what_would_change_mind": {"type": "array", "items": {"type": "string"}},
        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
        "evidence_citations": {"type": "array", "items": {"type": "string"}},
    },
    "required": [
        "narrative",
        "risk_level",
        "key_findings",
        "hypotheses",
        "known_facts",
        "unknowns",
        "what_would_change_mind",
        "confidence",
        "evidence_citations",
    ],
}

REASONING_MIN_MAX_TOKENS = 1024
REASONING_MAX_REPAIR_ATTEMPTS = 2
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

    @staticmethod
    def _repair_instruction(previous_response: str) -> str:
        preview = previous_response.strip().replace("\u0000", "")
        if len(preview) > 2000:
            preview = preview[:2000] + "…"
        return (
            "Your previous response did not meet the required format. "
            "Return ONLY a single RAW JSON object matching the schema in the system prompt "
            "(no markdown, no code fences, no commentary).\n\n"
            "Previous response (for reference):\n"
            f"{preview}"
        )

    async def execute(self, state: InvestigationState) -> InvestigationState:
        from app.core.config import get_settings

        settings = self._settings or get_settings()
        prompt_guard_enabled = settings.llm.prompt_guard_enabled
        reasoning_enabled = bool(
            get_attr(get_attr(settings, "features", None), "enable_llm_reasoning", True)
        )

        with tracer.start_as_current_span("tool.reasoning") as span:
            span.set_attribute("investigation_id", state["investigation_id"])
            span.set_attribute("tool_name", self.name)

            if not reasoning_enabled:
                span.set_attribute("reasoning_llm_enabled", False)
                message = "LLM reasoning disabled by OPS_AGENT_ENABLE_LLM_REASONING"
                logger.error(
                    "Reasoning tool LLM disabled by feature flag",
                    investigation_id=state["investigation_id"],
                    error=message,
                )
                raise RuntimeError(message)

            context = state["context"]
            pattern_results = state["pattern_results"]
            similarity_results = state["similarity_results"]
            link_analysis_results = state.get("link_analysis_results", {})

            redacted_context = redact_state_for_llm(context)
            prompt_payload = assemble_prompt_payload(
                context=redacted_context,
                pattern_analysis=pattern_results,
                similarity_analysis=similarity_results,
                link_analysis=link_analysis_results,
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
                    error_preview = "; ".join([str(err) for err in validation_errors[:5]])
                    raise ValueError(f"Prompt guard blocked: {error_preview}")

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
                async with asyncio.timeout(settings.llm.stage_timeout_seconds):
                    response = await self._llm.ainvoke(
                        messages,
                        max_tokens=max(
                            settings.llm.max_completion_tokens, REASONING_MIN_MAX_TOKENS
                        ),
                        request_timeout=float(settings.llm.stage_timeout_seconds),
                        response_format=REASONING_RESPONSE_FORMAT,
                    )
            except TimeoutError:
                elapsed = time.perf_counter() - start_time
                ops_agent_llm_latency_seconds.labels(purpose="reasoning").observe(elapsed)
                ops_agent_llm_calls_total.labels(purpose="reasoning", status="timeout").inc()
                span.set_attribute(
                    "error", f"reasoning_llm_timeout_{settings.llm.stage_timeout_seconds}s"
                )
                logger.warning(
                    "Reasoning tool LLM call timed out",
                    investigation_id=state["investigation_id"],
                    timeout_seconds=settings.llm.stage_timeout_seconds,
                )
                raise
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
                raise

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

            parse_attempt = 0
            current_content = response_content
            while True:
                try:
                    reasoning = parse_llm_response(current_content)
                    break
                except ValueError as exc:
                    status_label = "parse_error" if parse_attempt == 0 else "repair_parse_error"
                    ops_agent_llm_calls_total.labels(purpose="reasoning", status=status_label).inc()
                    logger.warning(
                        "Reasoning tool returned non-parseable payload",
                        investigation_id=state["investigation_id"],
                        attempt=parse_attempt + 1,
                        max_attempts=REASONING_MAX_REPAIR_ATTEMPTS + 1,
                        error=str(exc),
                        response_length=len(current_content),
                    )
                    span.add_event(
                        "llm.response_parse_error",
                        {
                            "purpose": "reasoning",
                            "attempt": parse_attempt + 1,
                            "error": str(exc)[:240],
                            "response_preview": current_content[:240],
                        },
                    )
                    if parse_attempt >= REASONING_MAX_REPAIR_ATTEMPTS:
                        raise

                    repair_messages = [
                        *messages,
                        HumanMessage(content=self._repair_instruction(current_content)),
                    ]

                    start_time = time.perf_counter()
                    try:
                        async with asyncio.timeout(settings.llm.stage_timeout_seconds):
                            repair_response = await self._llm.ainvoke(
                                repair_messages,
                                max_tokens=max(
                                    settings.llm.max_completion_tokens,
                                    REASONING_MIN_MAX_TOKENS,
                                ),
                                request_timeout=float(settings.llm.stage_timeout_seconds),
                                response_format=REASONING_RESPONSE_FORMAT,
                            )
                    except Exception as repair_exc:
                        elapsed = time.perf_counter() - start_time
                        ops_agent_llm_latency_seconds.labels(purpose="reasoning").observe(elapsed)
                        ops_agent_llm_calls_total.labels(
                            purpose="reasoning", status="repair_error"
                        ).inc()
                        span.set_attribute("error", str(repair_exc))
                        logger.error(
                            "Reasoning tool repair call failed",
                            investigation_id=state["investigation_id"],
                            attempt=parse_attempt + 1,
                            error=str(repair_exc),
                        )
                        raise

                    elapsed = time.perf_counter() - start_time
                    ops_agent_llm_latency_seconds.labels(purpose="reasoning").observe(elapsed)
                    current_content = str(repair_response.content)
                    span.add_event(
                        "llm.repair_response",
                        {
                            "purpose": "reasoning",
                            "attempt": parse_attempt + 1,
                            "content_length": len(current_content),
                        },
                    )
                    parse_attempt += 1

            if "summary" not in reasoning and isinstance(reasoning.get("narrative"), str):
                narrative = reasoning["narrative"].strip()
                if narrative:
                    reasoning["summary"] = narrative
            llm_status = "success"
            ops_agent_llm_calls_total.labels(purpose="reasoning", status=llm_status).inc()
            reasoning["llm_status"] = llm_status

            hypotheses = reasoning.get("hypotheses", [])
            severity = reasoning.get("risk_level", state["severity"])
            if severity not in VALID_SEVERITIES:
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

    @staticmethod
    def _normalize_severity(value: object, *, default: str) -> str:
        if isinstance(value, str):
            normalized = value.strip().upper()
            if normalized in VALID_SEVERITIES:
                return normalized
        return default

    @staticmethod
    def _max_severity(left: str, right: str) -> str:
        return left if SEVERITY_RANK.get(left, 0) >= SEVERITY_RANK.get(right, 0) else right

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
                get_attr(transaction, "three_ds_authenticated"),
            ),
            "trusted_device": (
                tx_context_dict.get("trusted_device"),
                get_attr(transaction, "device_trusted"),
                get_attr(transaction, "is_trusted_device"),
            ),
            "cardholder_present": (
                tx_context_dict.get("cardholder_present"),
                get_attr(transaction, "cardholder_present"),
            ),
            "recurring_customer": (
                tx_context_dict.get("is_recurring_customer"),
                get_attr(transaction, "is_recurring_customer"),
            ),
            "known_merchant": (
                tx_context_dict.get("known_merchant"),
                get_attr(transaction, "is_known_merchant"),
            ),
            "avs_match": (
                tx_context_dict.get("avs_match"),
                get_attr(transaction, "avs_match"),
            ),
            "cvv_match": (
                tx_context_dict.get("cvv_match"),
                get_attr(transaction, "cvv_match"),
            ),
            "tokenized": (
                tx_context_dict.get("tokenized"),
                tx_context_dict.get("payment_token_present"),
                get_attr(transaction, "is_tokenized"),
                get_attr(transaction, "payment_token_present"),
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
            counter = get_attr(match, "counter_evidence")
            if isinstance(counter, (list, dict)) and bool(counter):
                return True
        return False

    @classmethod
    def _decision(cls, state: InvestigationState) -> str:
        context = state.get("context", {}) if isinstance(state, dict) else {}
        context_dict = context if isinstance(context, dict) else {}
        transaction = context_dict.get("transaction", {})
        decision = get_attr(transaction, "decision") or get_attr(transaction, "status")
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
        amount_anomaly_score = score_by_name.get("amount_anomaly", 0.0)
        non_amount_pattern_max = max(
            (
                score
                for name, score in score_by_name.items()
                if name != "amount_anomaly" and isinstance(score, (int, float))
            ),
            default=0.0,
        )
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
        isolated_moderate_amount_anomaly = (
            amount_anomaly_score >= 0.65
            and amount_anomaly_score <= 0.72
            and non_amount_pattern_max <= 0.55
        )

        has_strong_counter_evidence = (
            (max_pattern_score <= 0.60 or isolated_moderate_amount_anomaly)
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
        if normalized == "LOW" and has_high_risk_pattern_combo:
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
