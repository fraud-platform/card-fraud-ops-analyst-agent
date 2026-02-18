"""Reasoning engine - LLM-powered analysis with fallback to deterministic."""

import asyncio
import logging
from typing import Any

import httpx

from app.agents.reasoning_core import (
    assemble_prompt_payload,
    merge_reasoning_with_evidence,
    parse_llm_response,
)
from app.agents.similarity_utils import get_similarity_score
from app.core.config import get_settings
from app.llm.consistency import check_consistency
from app.llm.prompts.investigation_v1 import get_investigation_template
from app.llm.prompts.investigation_v2 import get_investigation_template_v2
from app.llm.prompts.templates import render_template
from app.llm.provider import LLMProvider, get_llm_provider
from app.llm.redaction import (
    RedactionPolicy,
    detect_pii_in_values,
    redact_context,
    validate_prompt_payload,
)

logger = logging.getLogger(__name__)


class ReasoningEngine:
    """LLM reasoning engine with consistency checks and fallback."""

    def __init__(self, llm_provider: LLMProvider | None = None):
        self.llm_provider = llm_provider
        self.settings = get_settings()
        self.redaction_policy = RedactionPolicy()

    @staticmethod
    def _coerce_int(value: Any, *, default: int, minimum: int = 0) -> int:
        if isinstance(value, bool):
            parsed = default
        elif isinstance(value, int | float | str):
            try:
                parsed = int(value)
            except ValueError, TypeError:
                parsed = default
        else:
            parsed = default
        return max(minimum, parsed)

    async def reason(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        conflict_matrix: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Generate LLM reasoning with fallback to deterministic.

        Args:
            context: Transaction context
            pattern_analysis: Pattern scoring results
            similarity_analysis: Similarity analysis results

        Returns:
            Merged reasoning result, or None if LLM fails
        """
        if not self.settings.features.enable_llm_reasoning:
            logger.debug("LLM reasoning disabled, returning None")
            return None

        if self.llm_provider is None:
            try:
                self.llm_provider = get_llm_provider(self.settings)
            except (ValueError, ConnectionError, httpx.HTTPError) as e:
                logger.error(
                    "Failed to initialize LLM provider", exc_info=True, extra={"error": str(e)}
                )
                # SECURITY: Return structured error dict for observability
                return {
                    "error": "llm_provider_init_failed",
                    "error_detail": type(e).__name__,
                    "model_mode": "deterministic",
                }

        try:
            logger.debug(
                "Starting LLM reasoning",
                extra={"enable_llm": self.settings.features.enable_llm_reasoning},
            )
            payload = assemble_prompt_payload(
                context, pattern_analysis, similarity_analysis, conflict_matrix=conflict_matrix
            )
            logger.debug("Payload assembled", extra={"keys": list(payload.keys())})

            redacted_payload = redact_context(payload, self.redaction_policy)

            if self.settings.llm.prompt_guard_enabled:
                violations = validate_prompt_payload(redacted_payload, self.redaction_policy)
                if violations:
                    logger.warning(f"Prompt payload violations: {violations}")
                    return {
                        "error": "prompt_guard_failed",
                        "error_detail": "; ".join(violations),
                        "model_mode": "deterministic",
                    }

                pii_violations = detect_pii_in_values(redacted_payload)
                if pii_violations:
                    logger.warning(f"PII detected in prompt payload: {pii_violations}")
                    return {
                        "error": "pii_guard_failed",
                        "error_detail": "; ".join(pii_violations),
                        "model_mode": "deterministic",
                    }

            if self.settings.features.narrative_version == "v2":
                template = get_investigation_template_v2()
            else:
                template = get_investigation_template()
            messages, token_count = render_template(template, redacted_payload)

            if token_count > self.settings.llm.max_prompt_tokens:
                logger.warning(
                    f"Prompt exceeds token limit: {token_count} > {self.settings.llm.max_prompt_tokens}"
                )

            stage_timeout_s = self._coerce_int(
                getattr(self.settings.llm, "stage_timeout_seconds", None),
                default=20,
                minimum=1,
            )
            provider_timeout_s = self._coerce_int(
                getattr(self.settings.llm, "timeout", None),
                default=30,
                minimum=1,
            )
            provider_timeout_s = min(provider_timeout_s, stage_timeout_s)
            max_completion_tokens = self._coerce_int(
                getattr(self.settings.llm, "max_completion_tokens", None),
                default=384,
                minimum=64,
            )
            max_retries = self._coerce_int(
                getattr(self.settings.llm, "max_retries", None),
                default=1,
                minimum=0,
            )

            try:
                async with asyncio.timeout(stage_timeout_s):
                    response = await self.llm_provider.complete(
                        messages,
                        json_mode=True,
                        timeout=provider_timeout_s,
                        max_tokens=max_completion_tokens,
                        num_retries=max_retries,
                    )
            except TimeoutError:
                logger.warning(
                    "LLM reasoning timed out; falling back to deterministic summary",
                    extra={"timeout_seconds": stage_timeout_s},
                )
                return {
                    "error": "llm_timeout",
                    "error_detail": f"LLM stage timed out after {stage_timeout_s}s",
                    "model_mode": "deterministic",
                }

            logger.debug(
                "LLM raw response received",
                extra={"content_length": len(response.content)},
            )

            parsed = parse_llm_response(response.content)
            logger.debug(
                "Parsed LLM response",
                extra={"parse_error": parsed.get("parse_error", False)},
            )

            pattern_scores = (
                pattern_analysis.get("patterns") or pattern_analysis.get("pattern_scores") or []
            )
            similarity_score = get_similarity_score(similarity_analysis)

            deterministic_evidence = {
                "severity": pattern_analysis.get("severity", "MEDIUM"),
                "pattern_scores": pattern_scores,
                "similarity_score": similarity_score,
                "evidence": pattern_scores,
            }

            consistency = check_consistency(
                parsed,
                deterministic_evidence,
                threshold=self.settings.llm.consistency_threshold,
            )

            logger.debug(
                "Consistency check",
                extra={
                    "passed": consistency.passed,
                    "score": consistency.score,
                    "violations": consistency.violations,
                },
            )
            if not consistency.passed:
                logger.warning(
                    f"Consistency check failed: {consistency.violations}, score={consistency.score}"
                )
                # SECURITY: Return structured error dict for observability
                return {
                    "error": "consistency_check_failed",
                    "error_detail": f"violations={consistency.violations}, score={consistency.score}",
                    "model_mode": "deterministic",
                }

            merged = merge_reasoning_with_evidence(parsed, deterministic_evidence)
            merged["llm_latency_ms"] = response.latency_ms
            merged["llm_model"] = response.model
            merged["llm_usage"] = response.usage

            return merged

        except (
            ValueError,
            KeyError,
            httpx.HTTPError,
            ConnectionError,
            OSError,
        ) as e:
            logger.error("LLM reasoning failed", exc_info=True, extra={"error": str(e)})
            # SECURITY: Return structured error dict for observability
            return {
                "error": "llm_reasoning_failed",
                "error_detail": f"{type(e).__name__}: {str(e)}",
                "model_mode": "deterministic",
            }
