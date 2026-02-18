"""Pipeline - Linear orchestrator with OTel spans and per-stage timing."""

import asyncio
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.action_planner import build_action_plan
from app.agents.conflict_matrix import compute_conflict_matrix
from app.agents.context_builder import ContextBuilder
from app.agents.evidence_builder import EvidenceBuilder
from app.agents.explanation_builder import ExplanationBuilder
from app.agents.pattern_engine import PatternEngine
from app.agents.pattern_utils import to_pattern_dicts
from app.agents.reasoning_engine import ReasoningEngine
from app.agents.recommendation_engine import RecommendationEngine
from app.agents.similarity_engine import SimilarityEngine
from app.agents.similarity_utils import get_similarity_score
from app.core.config import get_settings
from app.core.metrics import (
    ops_agent_llm_calls_total,
    ops_agent_llm_consistency_score,
    ops_agent_llm_latency_seconds,
    ops_agent_llm_tokens_total,
    ops_agent_pipeline_stage_latency_seconds,
)
from app.persistence.insight_repository import InsightRepository
from app.persistence.run_repository import RunRepository
from app.utils.hashing import hash_llm_reasoning

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)


@dataclass(slots=True)
class PipelineState:
    """Canonical state exchanged between pipeline stages."""

    run_id: str
    mode: str
    transaction_id: str
    case_id: str | None = None
    context: dict[str, Any] | None = None
    pattern_analysis: dict[str, Any] | None = None
    similarity_analysis: dict[str, Any] | None = None
    conflict_matrix: dict[str, Any] | None = None
    llm_reasoning: dict[str, Any] | None = None
    recommendation_result: dict[str, Any] | None = None
    explanation: dict[str, Any] | None = None


class Pipeline:
    """Linear orchestrator for investigation pipeline."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.context_builder = ContextBuilder(session)
        self.pattern_engine = PatternEngine(session)
        self.similarity_engine = SimilarityEngine(session)
        self.recommendation_engine = RecommendationEngine(session)
        self.reasoning_engine = ReasoningEngine()
        self.run_repo = RunRepository(session)
        self.insight_repo = InsightRepository(session)
        self._settings = get_settings()
        self._evidence_builder = EvidenceBuilder()
        self._explanation_builder = ExplanationBuilder()

    async def run(
        self,
        run_id: str,
        mode: str,
        transaction_id: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        """Execute the full investigation pipeline.

        Security: Wrapped with asyncio.timeout to prevent indefinite hangs from
        slow/failed LLM calls or external services. 300s = 5 minutes maximum.
        """
        pipeline_start = time.perf_counter()
        stage_durations: dict[str, float] = {}
        runtime_feature_flags = self._runtime_feature_flags_snapshot()
        runtime_safeguards = self._runtime_safeguards_snapshot(runtime_feature_flags)

        # SECURITY: Prevent pipeline hangs from slow/failed LLM or external calls
        async with asyncio.timeout(300):  # 5 minutes maximum
            with tracer.start_as_current_span("ops_agent.pipeline") as pipeline_span:
                state = PipelineState(
                    run_id=run_id,
                    mode=mode,
                    transaction_id=transaction_id,
                    case_id=case_id,
                )
                pipeline_span.set_attribute("run.id", run_id)
                pipeline_span.set_attribute("run.mode", mode)
                pipeline_span.set_attribute("transaction.id", transaction_id)
                if case_id:
                    pipeline_span.set_attribute("run.case_id", case_id)

                try:
                    logger.info(
                        "Starting pipeline",
                        extra={"run_id": run_id, "transaction_id": transaction_id},
                    )

                    state.context = await self._timed_stage(
                        "context_build",
                        stage_durations,
                        self._context_build(transaction_id),
                    )
                    await self._transaction_checkpoint("post_context_build", run_id)

                    # Pattern and similarity analysis are independent - run in parallel
                    pattern_coro = self._timed_stage(
                        "pattern_analysis",
                        stage_durations,
                        self._pattern_analysis(state.context),
                    )
                    similarity_coro = self._timed_stage(
                        "similarity_analysis",
                        stage_durations,
                        self._similarity_analysis(state.context),
                    )
                    (
                        state.pattern_analysis,
                        state.similarity_analysis,
                    ) = await asyncio.gather(pattern_coro, similarity_coro)

                    # Release DB resources before the potentially long LLM stage.
                    await self._transaction_checkpoint("post_similarity", run_id)

                    # Set key fraud signals on the parent span for Jaeger search
                    severity = (state.pattern_analysis or {}).get("severity", "UNKNOWN")
                    pipeline_span.set_attribute("pattern.severity", severity)
                    pipeline_span.set_attribute(
                        "pattern.velocity_score",
                        float(to_pattern_dicts(state.pattern_analysis)[0].get("score", 0.0))
                        if to_pattern_dicts(state.pattern_analysis)
                        else 0.0,
                    )
                    similarity_score = self._similarity_score(state.similarity_analysis)
                    pipeline_span.set_attribute(
                        "similarity.score",
                        similarity_score,
                    )

                    # Conflict matrix analysis (feature-flagged)
                    if self._settings.features.conflict_matrix_enabled:
                        state.conflict_matrix = self._compute_conflict_matrix(
                            state.pattern_analysis, state.similarity_analysis
                        )
                        pipeline_span.set_attribute(
                            "conflict.score",
                            float(state.conflict_matrix.get("overall_conflict_score", 0.0)),
                        )

                    state.llm_reasoning = await self._timed_stage(
                        "llm_reasoning",
                        stage_durations,
                        self._llm_reasoning(
                            state.context,
                            state.pattern_analysis,
                            state.similarity_analysis,
                            state.conflict_matrix,
                        ),
                    )

                    # Record LLM metrics on the parent span
                    if state.llm_reasoning and "error" not in state.llm_reasoning:
                        self._record_llm_metrics(state.llm_reasoning, pipeline_span)
                    else:
                        ops_agent_llm_calls_total.labels(status="fallback").inc()

                    state.recommendation_result = await self._timed_stage(
                        "recommendations",
                        stage_durations,
                        self._recommendation_generation(
                            state.context,
                            state.pattern_analysis,
                            state.similarity_analysis,
                            transaction_id,
                            state.llm_reasoning,
                        ),
                    )

                    model_mode = (
                        state.llm_reasoning.get("model_mode", "deterministic")
                        if state.llm_reasoning
                        else "deterministic"
                    )
                    llm_status, llm_error, llm_model = self._llm_observability(
                        state.llm_reasoning, model_mode
                    )

                    # Build explanation (feature-flagged)
                    if self._settings.features.explanation_builder_enabled:
                        state.explanation = self._build_explanation(
                            state.context,
                            state.pattern_analysis,
                            state.similarity_analysis,
                            state.conflict_matrix,
                            state.llm_reasoning,
                        )

                    pipeline_span.set_attribute("run.model_mode", model_mode)
                    pipeline_span.set_attribute(
                        "recommendations.count",
                        len(state.recommendation_result.get("recommendations", [])),
                    )

                    await self._persist_evidence(
                        run_id=run_id,
                        context=state.context,
                        pattern_analysis=state.pattern_analysis,
                        similarity_analysis=state.similarity_analysis,
                        conflict_matrix=state.conflict_matrix,
                        llm_reasoning=state.llm_reasoning,
                        insight=(state.recommendation_result or {}).get("insight"),
                    )

                    duration_ms = (time.perf_counter() - pipeline_start) * 1000
                    pipeline_span.set_attribute("run.duration_ms", round(duration_ms, 1))
                    rounded_stage_durations = {k: round(v, 1) for k, v in stage_durations.items()}
                    recommendations = (state.recommendation_result or {}).get("recommendations", [])
                    action_plan, evidence_gaps = build_action_plan(
                        context=state.context or {},
                        pattern_analysis=state.pattern_analysis or {},
                        similarity_analysis=state.similarity_analysis or {},
                        recommendations=recommendations,
                        severity=severity,
                        llm_status=llm_status,
                    )
                    agentic_trace = self._build_agentic_trace(
                        run_id=run_id,
                        model_mode=model_mode,
                        llm_status=llm_status,
                        llm_error=llm_error,
                        llm_model=llm_model,
                        llm_reasoning=state.llm_reasoning,
                        stage_durations=rounded_stage_durations,
                        similarity_analysis=state.similarity_analysis or {},
                        recommendations=recommendations,
                        runtime_feature_flags=runtime_feature_flags,
                        runtime_safeguards=runtime_safeguards,
                    )

                    await self._complete_run(
                        run_id,
                        "SUCCESS",
                        model_mode=model_mode,
                        llm_status=llm_status,
                        llm_error=llm_error,
                        llm_model=llm_model,
                        duration_ms=round(duration_ms, 1),
                        stage_durations=rounded_stage_durations,
                        runtime_feature_flags=runtime_feature_flags,
                        runtime_safeguards=runtime_safeguards,
                    )
                    await self._transaction_checkpoint("finalize_success", run_id)

                    logger.info(
                        "Pipeline completed",
                        extra={
                            "run_id": run_id,
                            "model_mode": model_mode,
                            "llm_status": llm_status,
                            "severity": severity,
                            "duration_ms": round(duration_ms, 1),
                            "stage_durations_ms": rounded_stage_durations,
                        },
                    )

                    result: dict[str, Any] = {
                        "run_id": run_id,
                        "status": "SUCCESS",
                        "mode": mode,
                        "transaction_id": transaction_id,
                        "model_mode": model_mode,
                        "llm_status": llm_status,
                        "llm_error": llm_error,
                        "llm_model": llm_model,
                        "duration_ms": round(duration_ms, 1),
                        "stage_durations": rounded_stage_durations,
                        "runtime_feature_flags": runtime_feature_flags,
                        "runtime_safeguards": runtime_safeguards,
                        "agentic_trace": agentic_trace,
                        "action_plan": action_plan,
                        "evidence_gaps": evidence_gaps,
                        "insight": (state.recommendation_result or {}).get("insight"),
                        "recommendations": recommendations,
                    }
                    if state.conflict_matrix is not None:
                        result["conflict_matrix"] = state.conflict_matrix
                    if state.explanation is not None:
                        result["explanation"] = state.explanation
                    return result

                except (
                    ValueError,
                    KeyError,
                    ConnectionError,
                    OSError,
                    TimeoutError,
                ) as e:
                    pipeline_span.record_exception(e)
                    pipeline_span.set_attribute("run.status", "FAILED")
                    logger.exception("Pipeline failed", extra={"run_id": run_id, "error": str(e)})
                    duration_ms = (time.perf_counter() - pipeline_start) * 1000
                    rounded_stage_durations = {k: round(v, 1) for k, v in stage_durations.items()}
                    await self._complete_run(
                        run_id,
                        "FAILED",
                        error_summary=str(e),
                        model_mode="deterministic",
                        llm_status="failed",
                        llm_error=str(e),
                        duration_ms=round(duration_ms, 1),
                        stage_durations=rounded_stage_durations,
                        runtime_feature_flags=runtime_feature_flags,
                        runtime_safeguards=runtime_safeguards,
                    )
                    await self._transaction_checkpoint("finalize_failure", run_id)
                    raise

    # ---------------------------------------------------------------------------
    # Stage helpers
    # ---------------------------------------------------------------------------

    async def _transaction_checkpoint(self, checkpoint: str, run_id: str) -> None:
        """Commit current unit-of-work and release pooled DB connection quickly."""
        try:
            await self.session.commit()
        except Exception:
            logger.exception(
                "Pipeline transaction checkpoint failed",
                extra={"run_id": run_id, "checkpoint": checkpoint},
            )
            await self.session.rollback()
            raise

    async def _timed_stage(self, stage_name: str, durations: dict[str, float], coro: Any) -> Any:
        """Run a coroutine, record its wall-clock duration, emit a metric and span."""
        with tracer.start_as_current_span(f"ops_agent.{stage_name}") as span:
            t0 = time.perf_counter()
            try:
                result = await coro
                elapsed = time.perf_counter() - t0
                durations[stage_name] = elapsed * 1000  # store as ms
                ops_agent_pipeline_stage_latency_seconds.labels(stage=stage_name).observe(elapsed)
                span.set_attribute("stage.duration_ms", round(elapsed * 1000, 1))
                return result
            except (
                ValueError,
                KeyError,
                ConnectionError,
                OSError,
                TimeoutError,
            ) as e:
                span.record_exception(e)
                raise

    def _record_llm_metrics(self, reasoning_result: dict[str, Any], span: trace.Span) -> None:
        """Record LLM observability signals from the reasoning result."""
        ops_agent_llm_calls_total.labels(status="success").inc()

        latency_ms = reasoning_result.get("llm_latency_ms", 0)
        if latency_ms:
            ops_agent_llm_latency_seconds.observe(latency_ms / 1000.0)
            span.set_attribute("llm.latency_ms", round(latency_ms, 1))

        model = reasoning_result.get("llm_model", "")
        if model:
            span.set_attribute("llm.model", model)

        usage = reasoning_result.get("llm_usage", {}) or {}
        prompt_tokens = usage.get("prompt_tokens", 0) or 0
        completion_tokens = usage.get("completion_tokens", 0) or 0
        if prompt_tokens:
            ops_agent_llm_tokens_total.labels(type="prompt").inc(prompt_tokens)
            span.set_attribute("llm.prompt_tokens", prompt_tokens)
        if completion_tokens:
            ops_agent_llm_tokens_total.labels(type="completion").inc(completion_tokens)
            span.set_attribute("llm.completion_tokens", completion_tokens)

        # Consistency score lives in the merged result
        confidence = reasoning_result.get("confidence")
        if confidence is not None:
            ops_agent_llm_consistency_score.observe(float(confidence))
            span.set_attribute("llm.confidence", float(confidence))

    # ---------------------------------------------------------------------------
    # Stage implementations
    # ---------------------------------------------------------------------------

    async def _context_build(self, transaction_id: str) -> dict[str, Any]:
        """Phase 1: Build context."""
        return await self.context_builder.build(transaction_id)

    async def _pattern_analysis(self, context: dict[str, Any]) -> dict[str, Any]:
        """Phase 2: Pattern analysis."""
        return await self.pattern_engine.analyze(context)

    async def _similarity_analysis(self, context: dict[str, Any]) -> dict[str, Any]:
        """Phase 3: Similarity analysis."""
        return await self.similarity_engine.analyze(context)

    async def _llm_reasoning(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        conflict_matrix: dict[str, Any] | None = None,
    ) -> dict[str, Any] | None:
        """Phase 4: LLM reasoning with fallback to deterministic."""
        return await self.reasoning_engine.reason(
            context, pattern_analysis, similarity_analysis, conflict_matrix=conflict_matrix
        )

    async def _recommendation_generation(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        transaction_id: str,
        reasoning: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Phase 5: Recommendation generation."""
        return await self.recommendation_engine.generate(
            context, pattern_analysis, similarity_analysis, transaction_id, reasoning
        )

    @staticmethod
    def _pattern_dicts(pattern_analysis: dict[str, Any] | None) -> list[dict[str, Any]]:
        return to_pattern_dicts(pattern_analysis)

    @staticmethod
    def _similarity_score(similarity_analysis: dict[str, Any] | None) -> float:
        return get_similarity_score(similarity_analysis)

    def _compute_conflict_matrix(
        self,
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
    ) -> dict[str, Any]:
        """Compute conflict matrix from pattern and similarity results."""
        overall_score = self._similarity_score(similarity_analysis)
        counter_evidence_list = self._counter_evidence_items(similarity_analysis)

        matrix = compute_conflict_matrix(
            pattern_analysis=pattern_analysis,
            similarity_score=overall_score,
            counter_evidence=counter_evidence_list,
        )
        return matrix.to_dict()

    @staticmethod
    def _counter_evidence_items(similarity_analysis: dict[str, Any]) -> list[Any]:
        from app.agents.conflict_matrix import CounterEvidence

        candidates = []
        similarity_result = similarity_analysis.get("similarity_result")
        if similarity_result is not None and hasattr(similarity_result, "counter_evidence"):
            result_counter_evidence = similarity_result.counter_evidence
            if result_counter_evidence:
                candidates.extend(result_counter_evidence)
        if similarity_analysis.get("counter_evidence"):
            candidates.extend(similarity_analysis.get("counter_evidence"))

        out: list[CounterEvidence] = []
        for entry in candidates:
            if not isinstance(entry, dict):
                continue
            evidence_items = entry.get("counter_evidence", [])
            if not evidence_items and "type" in entry:
                evidence_items = [entry]
            for evidence in evidence_items:
                if not isinstance(evidence, dict):
                    continue
                out.append(
                    CounterEvidence(
                        evidence_type=str(evidence.get("type", "unknown")),
                        strength=float(evidence.get("strength", 0.0)),
                        description=str(evidence.get("description", "")),
                        supporting_data=evidence,
                    )
                )
        return out

    def _build_explanation(
        self,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        conflict_matrix: dict[str, Any] | None,
        llm_reasoning: dict[str, Any] | None,
    ) -> dict[str, Any]:
        """Build human-readable explanation."""
        similarity_result = similarity_analysis.get("similarity_result")
        if similarity_result is not None:
            sim_dict: dict[str, Any] = {
                "matches": [
                    {
                        "match_id": m.match_id,
                        "match_type": m.match_type,
                        "similarity_score": m.similarity_score,
                        "details": m.details,
                        "counter_evidence": m.counter_evidence,
                    }
                    for m in getattr(similarity_result, "matches", [])
                ],
                "overall_score": getattr(similarity_result, "overall_score", 0.0),
            }
        else:
            sim_dict = similarity_analysis

        explanation = self._explanation_builder.build(
            context=context,
            pattern_analysis=pattern_analysis,
            similarity_result=sim_dict,
            conflict_matrix=conflict_matrix,
            llm_reasoning=llm_reasoning,
        )
        return {
            "investigation_id": explanation.investigation_id,
            "transaction_id": explanation.transaction_id,
            "markdown": explanation.to_markdown(),
            "metadata": explanation.metadata,
            "generated_at": explanation.generated_at.isoformat(),
        }

    async def _complete_run(
        self,
        run_id: str,
        status: str,
        error_summary: str | None = None,
        *,
        model_mode: str | None = None,
        llm_status: str | None = None,
        llm_error: str | None = None,
        llm_model: str | None = None,
        duration_ms: float | None = None,
        stage_durations: dict[str, float] | None = None,
        runtime_feature_flags: dict[str, bool] | None = None,
        runtime_safeguards: dict[str, bool] | None = None,
    ) -> None:
        """Complete the run."""
        await self.run_repo.complete(
            run_id,
            status,
            error_summary,
            model_mode=model_mode,
            llm_status=llm_status,
            llm_error=llm_error,
            llm_model=llm_model,
            duration_ms=duration_ms,
            stage_durations=stage_durations,
            runtime_feature_flags=runtime_feature_flags,
            runtime_safeguards=runtime_safeguards,
        )

    def _llm_observability(
        self,
        llm_reasoning: dict[str, Any] | None,
        model_mode: str,
    ) -> tuple[str, str | None, str | None]:
        """Normalize LLM execution status for run-level audit fields."""
        if not self._settings.features.enable_llm_reasoning:
            return "disabled", None, None
        if llm_reasoning is None:
            return "skipped", None, None
        if llm_reasoning.get("error"):
            error_detail = llm_reasoning.get("error_detail") or llm_reasoning.get("error")
            return "fallback", str(error_detail), None
        llm_model = llm_reasoning.get("llm_model")
        # Keep run-level model explicit for audit trails even when model_mode is deterministic.
        if model_mode != "hybrid":
            return "deterministic", None, str(llm_model) if llm_model else None
        return "success", None, str(llm_model) if llm_model else None

    def _build_agentic_trace(
        self,
        *,
        run_id: str,
        model_mode: str,
        llm_status: str,
        llm_error: str | None,
        llm_model: str | None,
        llm_reasoning: dict[str, Any] | None,
        stage_durations: dict[str, float],
        similarity_analysis: dict[str, Any],
        recommendations: list[dict[str, Any]],
        runtime_feature_flags: dict[str, bool],
        runtime_safeguards: dict[str, bool],
    ) -> dict[str, Any]:
        """Build structured agentic execution trace for audit and enterprise reporting."""
        llm_latency_ms = None
        llm_reasoning_hash = None
        if llm_reasoning:
            raw_latency = llm_reasoning.get("llm_latency_ms")
            if isinstance(raw_latency, int | float):
                llm_latency_ms = round(float(raw_latency), 1)
            llm_reasoning_hash = hash_llm_reasoning(llm_reasoning)

        if llm_latency_ms is None or llm_reasoning_hash is None:
            payload_latency, payload_hash = self._llm_metadata_from_recommendations(recommendations)
            llm_latency_ms = llm_latency_ms if llm_latency_ms is not None else payload_latency
            llm_reasoning_hash = llm_reasoning_hash or payload_hash

        vector_feature_enabled = bool(similarity_analysis.get("vector_feature_enabled"))
        vector_stage_executed = bool(similarity_analysis.get("vector_stage_executed"))
        vector_status = (
            str(similarity_analysis.get("vector_status"))
            if similarity_analysis.get("vector_status") is not None
            else ("disabled" if not vector_feature_enabled else "unknown")
        )
        vector_error = similarity_analysis.get("vector_error")
        vector_match_count = int(similarity_analysis.get("vector_match_count") or 0)
        attribute_match_count = int(similarity_analysis.get("attribute_match_count") or 0)

        llm_stage_status = self._llm_stage_status(llm_status, stage_durations)
        similarity_stage_status = self._stage_status("similarity_analysis", stage_durations)

        return {
            "run_id": run_id,
            "model_mode": model_mode,
            "llm_status": llm_status,
            "llm_model": llm_model,
            "llm_error": llm_error,
            "llm_latency_ms": llm_latency_ms,
            "llm_reasoning_hash": llm_reasoning_hash,
            "stage_durations": stage_durations,
            "stages": {
                "context_build": {
                    "enabled": True,
                    "status": self._stage_status("context_build", stage_durations),
                    "duration_ms": stage_durations.get("context_build"),
                    "metadata": {},
                },
                "pattern_analysis": {
                    "enabled": True,
                    "status": self._stage_status("pattern_analysis", stage_durations),
                    "duration_ms": stage_durations.get("pattern_analysis"),
                    "metadata": {},
                },
                "similarity_analysis": {
                    "enabled": True,
                    "status": similarity_stage_status,
                    "duration_ms": stage_durations.get("similarity_analysis"),
                    "metadata": {
                        "vector_feature_enabled": vector_feature_enabled,
                        "vector_stage_executed": vector_stage_executed,
                        "vector_status": vector_status,
                        "vector_error": vector_error,
                        "vector_match_count": vector_match_count,
                        "attribute_match_count": attribute_match_count,
                    },
                },
                "llm_reasoning": {
                    "enabled": bool(runtime_feature_flags.get("enable_llm_reasoning", False)),
                    "status": llm_stage_status,
                    "duration_ms": stage_durations.get("llm_reasoning"),
                    "metadata": {
                        "model": llm_model,
                        "error": llm_error,
                    },
                },
                "recommendations": {
                    "enabled": True,
                    "status": self._stage_status("recommendations", stage_durations),
                    "duration_ms": stage_durations.get("recommendations"),
                    "metadata": {"count": len(recommendations)},
                },
            },
            "feature_flags": runtime_feature_flags,
            "safeguards": runtime_safeguards,
        }

    def _runtime_feature_flags_snapshot(self) -> dict[str, bool]:
        return {
            "enable_deterministic_pipeline": bool(
                self._settings.features.enable_deterministic_pipeline
            ),
            "enable_llm_reasoning": bool(self._settings.features.enable_llm_reasoning),
            "vector_search_enabled": bool(self._settings.vector_search.enabled),
            "counter_evidence_enabled": bool(self._settings.features.counter_evidence_enabled),
            "conflict_matrix_enabled": bool(self._settings.features.conflict_matrix_enabled),
            "explanation_builder_enabled": bool(
                self._settings.features.explanation_builder_enabled
            ),
            "enable_rule_draft_export": bool(self._settings.features.enable_rule_draft_export),
            "enforce_human_approval": bool(self._settings.features.enforce_human_approval),
        }

    def _runtime_safeguards_snapshot(
        self, runtime_feature_flags: dict[str, bool]
    ) -> dict[str, bool]:
        vector_enabled = bool(runtime_feature_flags.get("vector_search_enabled", False))
        llm_enabled = bool(runtime_feature_flags.get("enable_llm_reasoning", False))
        return {
            "human_approval_enforced": bool(runtime_feature_flags.get("enforce_human_approval")),
            "prompt_guard_enabled": bool(self._settings.llm.prompt_guard_enabled),
            "consistency_check_enabled": llm_enabled,
            "vector_fail_closed": vector_enabled,
        }

    @staticmethod
    def _stage_status(stage_name: str, stage_durations: dict[str, float]) -> str:
        """Get canonical stage status from the duration map."""
        return "success" if stage_name in stage_durations else "skipped"

    def _llm_stage_status(self, llm_status: str, stage_durations: dict[str, float]) -> str:
        """Get the LLM stage status with fallback/disabled handling."""
        if not self._settings.features.enable_llm_reasoning:
            return "disabled"
        if llm_status in {"fallback", "failed"}:
            return "fallback"
        return self._stage_status("llm_reasoning", stage_durations)

    def _build_action_plan(
        self,
        *,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        recommendations: list[dict[str, Any]],
        severity: str,
        llm_status: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Compatibility wrapper around the shared action planner."""
        return build_action_plan(
            context=context,
            pattern_analysis=pattern_analysis,
            similarity_analysis=similarity_analysis,
            recommendations=recommendations,
            severity=severity,
            llm_status=llm_status,
        )

    @staticmethod
    def _reasoning_hash(llm_reasoning: dict[str, Any]) -> str | None:
        return hash_llm_reasoning(llm_reasoning)

    @staticmethod
    def _llm_metadata_from_recommendations(
        recommendations: list[dict[str, Any]],
    ) -> tuple[float | None, str | None]:
        llm_latency_ms: float | None = None
        llm_reasoning_hash: str | None = None
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            payload = rec.get("payload")
            if not isinstance(payload, dict):
                continue
            raw_latency = payload.get("llm_latency_ms")
            if llm_latency_ms is None and isinstance(raw_latency, int | float):
                llm_latency_ms = round(float(raw_latency), 1)
            raw_hash = payload.get("llm_reasoning_hash")
            if llm_reasoning_hash is None and isinstance(raw_hash, str) and raw_hash:
                llm_reasoning_hash = raw_hash
            if llm_latency_ms is not None and llm_reasoning_hash is not None:
                break
        return llm_latency_ms, llm_reasoning_hash

    async def _persist_evidence(
        self,
        run_id: str,
        context: dict[str, Any],
        pattern_analysis: dict[str, Any],
        similarity_analysis: dict[str, Any],
        conflict_matrix: dict[str, Any] | None,
        llm_reasoning: dict[str, Any] | None,
        insight: dict[str, Any] | None,
    ) -> None:
        """Persist structured evidence envelopes for analyst auditability."""
        if not insight:
            return

        insight_id = insight.get("insight_id")
        if not insight_id:
            return

        transaction = context.get("transaction")
        tx_timestamp: datetime | None
        if isinstance(transaction, dict):
            tx_timestamp = transaction.get("transaction_timestamp")
        else:
            tx_timestamp = getattr(transaction, "transaction_timestamp", None)

        for pattern in self._pattern_dicts(pattern_analysis):
            envelope = self._evidence_builder.build_pattern_evidence(
                investigation_id=run_id,
                pattern_name=str(pattern.get("pattern_name", "unknown")),
                score=float(pattern.get("score", 0.0)),
                description=f"Pattern {pattern.get('pattern_name', 'unknown')} detected",
                supporting_data={
                    "details": pattern.get("details", {}),
                    "related_transaction_ids": [],
                },
                transaction_timestamp=tx_timestamp,
            )
            await self.insight_repo.add_evidence(
                insight_id=insight_id,
                evidence_kind=envelope.evidence_kind,
                evidence_payload=envelope.to_jsonb(),
            )

        similarity_result = similarity_analysis.get("similarity_result")
        if similarity_result is not None:
            for match in getattr(similarity_result, "matches", []):
                envelope = self._evidence_builder.build_similarity_evidence(
                    investigation_id=run_id,
                    match={
                        "match_id": getattr(match, "match_id", ""),
                        "match_type": getattr(match, "match_type", "unknown"),
                        "similarity_score": float(getattr(match, "similarity_score", 0.0)),
                        "details": getattr(match, "details", {}),
                        "counter_evidence": getattr(match, "counter_evidence", None),
                    },
                )
                await self.insight_repo.add_evidence(
                    insight_id=insight_id,
                    evidence_kind=envelope.evidence_kind,
                    evidence_payload=envelope.to_jsonb(),
                )

            counter_entries = getattr(similarity_result, "counter_evidence", None) or []
            for entry in counter_entries:
                if not isinstance(entry, dict):
                    continue
                for evidence in entry.get("counter_evidence", []):
                    if not isinstance(evidence, dict):
                        continue
                    envelope = self._evidence_builder.build_counter_evidence(
                        investigation_id=run_id,
                        evidence_type=str(evidence.get("type", "unknown")),
                        strength=float(evidence.get("strength", 0.0)),
                        description=str(evidence.get("description", "")),
                        supporting_data=evidence,
                    )
                    await self.insight_repo.add_evidence(
                        insight_id=insight_id,
                        evidence_kind=envelope.evidence_kind,
                        evidence_payload=envelope.to_jsonb(),
                    )

        if conflict_matrix is not None:
            envelope = self._evidence_builder.build_conflict_evidence(
                investigation_id=run_id,
                conflict_matrix=conflict_matrix,
            )
            await self.insight_repo.add_evidence(
                insight_id=insight_id,
                evidence_kind=envelope.evidence_kind,
                evidence_payload=envelope.to_jsonb(),
            )

        if llm_reasoning and "error" not in llm_reasoning:
            envelope = self._evidence_builder.build_llm_reasoning_evidence(
                investigation_id=run_id,
                llm_reasoning=llm_reasoning,
            )
            await self.insight_repo.add_evidence(
                insight_id=insight_id,
                evidence_kind=envelope.evidence_kind,
                evidence_payload=envelope.to_jsonb(),
            )
