"""Investigation service - orchestrates the investigation pipeline."""

import time
from typing import Any

from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.agents.action_planner import build_action_plan
from app.agents.pipeline import Pipeline
from app.core.config import get_settings
from app.core.errors import ConflictError, ValidationError
from app.core.metrics import (
    ops_agent_investigation_latency_seconds,
    ops_agent_investigation_requests_total,
    ops_agent_recommendations_generated_total,
)
from app.persistence.insight_repository import InsightRepository
from app.persistence.recommendation_repository import RecommendationRepository
from app.persistence.run_repository import RunRepository
from app.utils.hashing import hash_summary_text


class InvestigationService:
    """Service for running investigations."""

    def __init__(self, session: AsyncSession):
        self.session = session
        self.run_repo = RunRepository(session)
        self.insight_repo = InsightRepository(session)
        self.recommendation_repo = RecommendationRepository(session)
        self.pipeline = Pipeline(session)

    async def run_investigation(
        self,
        mode: str,
        transaction_id: str,
        case_id: str | None = None,
    ) -> dict[str, Any]:
        """Run an investigation for a transaction."""
        settings = get_settings()

        if not settings.features.enable_deterministic_pipeline:
            raise ValidationError("Deterministic pipeline is not enabled")

        runtime_feature_flags = self._runtime_feature_flags_snapshot(settings)
        runtime_safeguards = self._runtime_safeguards_snapshot(
            settings=settings, runtime_feature_flags=runtime_feature_flags
        )

        try:
            run = await self.run_repo.create(
                mode=mode,
                transaction_id=transaction_id,
                case_id=case_id,
                runtime_feature_flags=runtime_feature_flags,
                runtime_safeguards=runtime_safeguards,
            )
            # Persist early so long-running pipeline stages do not hold the
            # initial run creation transaction open.
            await self.session.commit()
        except IntegrityError:
            # Duplicate trigger_ref - investigation already exists for this transaction.
            # Must rollback the session before any further queries (SQLAlchemy async
            # sessions are in a FAILED state after an IntegrityError).
            await self.session.rollback()
            trigger_ref = f"transaction:{transaction_id}" + (f" case:{case_id}" if case_id else "")
            existing = await self.run_repo.get_by_trigger_ref(trigger_ref)
            if existing is None:
                raise
            raise ConflictError(
                "Investigation already exists for this transaction",
                details={"run_id": existing["run_id"], "status": existing["status"]},
            ) from None

        t0 = time.perf_counter()
        try:
            result = await self.pipeline.run(
                run_id=run["run_id"],
                mode=mode,
                transaction_id=transaction_id,
                case_id=case_id,
            )
        except Exception:
            elapsed = time.perf_counter() - t0
            ops_agent_investigation_requests_total.labels(mode=mode, status="error").inc()
            ops_agent_investigation_latency_seconds.labels(mode=mode).observe(elapsed)
            raise

        elapsed = time.perf_counter() - t0
        ops_agent_investigation_requests_total.labels(mode=mode, status="success").inc()
        ops_agent_investigation_latency_seconds.labels(mode=mode).observe(elapsed)

        severity = (result.get("insight") or {}).get("severity", "UNKNOWN")
        for rec in result.get("recommendations", []):
            ops_agent_recommendations_generated_total.labels(
                type=rec.get("type", "unknown"),
                severity=severity,
            ).inc()

        return result

    async def get_investigation(self, run_id: str) -> dict[str, Any] | None:
        """Get investigation by run ID with insights and recommendations."""
        run = await self.run_repo.get(run_id)
        if run is None:
            return None

        # Parse transaction_id from trigger_ref ("transaction:<id>" or "transaction:<id> case:<id>")
        trigger_ref = run.get("trigger_ref", "")
        transaction_id = ""
        case_id = None
        for part in trigger_ref.split():
            if part.startswith("transaction:"):
                transaction_id = part[len("transaction:") :]
            elif part.startswith("case:"):
                case_id = part[len("case:") :]

        result: dict[str, Any] = {
            "run_id": run["run_id"],
            "status": run["status"],
            "mode": run["mode"],
            "transaction_id": transaction_id,
            "case_id": case_id,
            "started_at": run["started_at"],
            "completed_at": run.get("completed_at"),
            "error_summary": run.get("error_summary"),
            "model_mode": run.get("model_mode") or "deterministic",
            "llm_status": run.get("llm_status"),
            "llm_error": run.get("llm_error"),
            "llm_model": run.get("llm_model"),
            "duration_ms": run.get("duration_ms"),
            "stage_durations": run.get("stage_durations") or {},
            "runtime_feature_flags": self._coerce_bool_map(run.get("runtime_feature_flags")),
            "runtime_safeguards": self._coerce_bool_map(run.get("runtime_safeguards")),
            "evidence": [],
            "recommendations": [],
            "action_plan": [],
            "evidence_gaps": [],
        }

        severity = "UNKNOWN"
        if transaction_id and run["status"] == "SUCCESS":
            insights = await self.insight_repo.get_insights_with_evidence(transaction_id)
            if insights:
                latest = insights[0]
                result["insight"] = latest
                result["evidence"] = list(latest.get("evidence", []))
                result["model_mode"] = latest.get("model_mode", result["model_mode"])
                severity = str(latest.get("severity") or "UNKNOWN")

                # Fetch recommendations for this insight using indexed query.
                result["recommendations"] = await self.recommendation_repo.list_by_insight_id(
                    latest["insight_id"]
                )

        runtime_feature_flags = (
            result["runtime_feature_flags"]
            if isinstance(result["runtime_feature_flags"], dict)
            else {}
        )
        vector_feature_enabled_default = bool(
            runtime_feature_flags.get("vector_search_enabled", get_settings().vector_search.enabled)
        )

        context_snapshot, pattern_analysis, similarity_analysis = (
            self._hydrate_stage_inputs_from_evidence(
                result["evidence"],
                stage_durations=result["stage_durations"],
                vector_feature_enabled_default=vector_feature_enabled_default,
            )
        )
        action_plan, evidence_gaps = build_action_plan(
            recommendations=result["recommendations"],
            context=context_snapshot,
            pattern_analysis=pattern_analysis,
            similarity_analysis=similarity_analysis,
            evidence=result["evidence"],
            severity=severity,
            llm_status=str(result.get("llm_status") or ""),
        )
        result["action_plan"] = action_plan
        result["evidence_gaps"] = evidence_gaps
        result["agentic_trace"] = self._build_agentic_trace(
            run=result,
            recommendations=result["recommendations"],
            evidence=result["evidence"],
            runtime_feature_flags=runtime_feature_flags,
            runtime_safeguards=(
                result["runtime_safeguards"]
                if isinstance(result["runtime_safeguards"], dict)
                else {}
            ),
        )

        return result

    @staticmethod
    def _build_agentic_trace(
        *,
        run: dict[str, Any],
        recommendations: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        runtime_feature_flags: dict[str, bool],
        runtime_safeguards: dict[str, bool],
    ) -> dict[str, Any]:
        stage_durations = run.get("stage_durations")
        durations = stage_durations if isinstance(stage_durations, dict) else {}

        llm_latency_ms: float | None = None
        llm_reasoning_hash: str | None = None
        for rec in recommendations:
            if not isinstance(rec, dict):
                continue
            payload = rec.get("payload")
            if not isinstance(payload, dict):
                continue
            latency = payload.get("llm_latency_ms")
            if llm_latency_ms is None and isinstance(latency, (int, float)):
                llm_latency_ms = round(float(latency), 1)
            hash_value = payload.get("llm_reasoning_hash")
            if llm_reasoning_hash is None and isinstance(hash_value, str) and hash_value:
                llm_reasoning_hash = hash_value
            if llm_latency_ms is not None and llm_reasoning_hash is not None:
                break

        if llm_reasoning_hash is None:
            llm_reasoning_hash = InvestigationService._hash_summary_for_audit(run)

        vector_count = 0
        attribute_count = 0
        for item in evidence:
            if not isinstance(item, dict):
                continue
            payload = item.get("evidence_payload")
            if not isinstance(payload, dict):
                continue
            evidence_kind = str(
                item.get("evidence_kind") or payload.get("evidence_kind") or ""
            ).lower()
            if evidence_kind != "similarity":
                continue
            supporting_data = (
                payload.get("supporting_data")
                if isinstance(payload.get("supporting_data"), dict)
                else {}
            )
            match_type = str(
                supporting_data.get("match_type") or payload.get("category") or ""
            ).lower()
            if match_type == "vector":
                vector_count += 1
                continue
            if match_type == "attribute":
                attribute_count += 1
                continue

            # Backward-compatible fallback for legacy payload shape.
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            source = str(metadata.get("source", "")).lower()
            if source == "vector":
                vector_count += 1
            elif source == "attribute":
                attribute_count += 1

        has_similarity_stage = "similarity_analysis" in durations
        vector_feature_enabled = bool(runtime_feature_flags.get("vector_search_enabled", False))
        vector_stage_executed = bool(vector_feature_enabled and has_similarity_stage)
        has_llm_stage = "llm_reasoning" in durations
        llm_status = str(run.get("llm_status") or "unknown")
        llm_feature_enabled = bool(runtime_feature_flags.get("enable_llm_reasoning", False))
        if llm_status == "disabled":
            llm_stage_status = "disabled"
        elif llm_status in {"fallback", "failed"}:
            llm_stage_status = "fallback"
        else:
            llm_stage_status = "success" if has_llm_stage else "skipped"

        return {
            "run_id": run.get("run_id"),
            "model_mode": run.get("model_mode") or "deterministic",
            "llm_status": run.get("llm_status"),
            "llm_model": run.get("llm_model"),
            "llm_error": run.get("llm_error"),
            "llm_latency_ms": llm_latency_ms,
            "llm_reasoning_hash": llm_reasoning_hash,
            "stage_durations": durations,
            "stages": {
                "context_build": {
                    "enabled": True,
                    "status": "success" if "context_build" in durations else "skipped",
                    "duration_ms": durations.get("context_build"),
                    "metadata": {},
                },
                "pattern_analysis": {
                    "enabled": True,
                    "status": "success" if "pattern_analysis" in durations else "skipped",
                    "duration_ms": durations.get("pattern_analysis"),
                    "metadata": {},
                },
                "similarity_analysis": {
                    "enabled": True,
                    "status": "success" if has_similarity_stage else "skipped",
                    "duration_ms": durations.get("similarity_analysis"),
                    "metadata": {
                        "vector_feature_enabled": vector_feature_enabled,
                        "vector_stage_executed": vector_stage_executed,
                        "vector_match_count": vector_count,
                        "attribute_match_count": attribute_count,
                    },
                },
                "llm_reasoning": {
                    "enabled": llm_feature_enabled,
                    "status": llm_stage_status,
                    "duration_ms": durations.get("llm_reasoning"),
                    "metadata": {
                        "model": run.get("llm_model"),
                        "error": run.get("llm_error"),
                    },
                },
                "recommendations": {
                    "enabled": True,
                    "status": "success" if "recommendations" in durations else "skipped",
                    "duration_ms": durations.get("recommendations"),
                    "metadata": {"count": len(recommendations)},
                },
            },
            "feature_flags": runtime_feature_flags,
            "safeguards": runtime_safeguards,
        }

    @staticmethod
    def _hash_summary_for_audit(run: dict[str, Any]) -> str | None:
        insight = run.get("insight")
        if not isinstance(insight, dict):
            return None
        summary = str(insight.get("summary", "")).strip()
        return hash_summary_text(summary)

    @staticmethod
    def _hydrate_stage_inputs_from_evidence(
        evidence: list[dict[str, Any]],
        *,
        stage_durations: dict[str, Any] | None = None,
        vector_feature_enabled_default: bool,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        """Reconstruct stage payloads from persisted evidence for detail-time action plans."""
        context_snapshot: dict[str, Any] = {}
        patterns: list[dict[str, Any]] = []
        similarity_matches: list[dict[str, Any]] = []
        vector_match_count = 0
        attribute_match_count = 0

        for item in evidence:
            if not isinstance(item, dict):
                continue
            payload = item.get("evidence_payload")
            if not isinstance(payload, dict):
                continue

            evidence_kind = str(
                item.get("evidence_kind") or payload.get("evidence_kind") or ""
            ).lower()
            supporting_data = (
                payload.get("supporting_data")
                if isinstance(payload.get("supporting_data"), dict)
                else {}
            )

            if evidence_kind == "context_snapshot":
                if supporting_data:
                    context_snapshot = dict(supporting_data)
                continue

            if evidence_kind == "pattern":
                pattern_name = str(
                    payload.get("category") or supporting_data.get("pattern_name") or ""
                ).strip()
                if not pattern_name:
                    continue
                details = supporting_data.get("details")
                patterns.append(
                    {
                        "pattern_name": pattern_name,
                        "score": InvestigationService._coerce_float(payload.get("strength")),
                        "details": details if isinstance(details, dict) else {},
                    }
                )
                continue

            if evidence_kind != "similarity":
                continue

            details = supporting_data.get("details")
            match_type = str(
                supporting_data.get("match_type") or payload.get("category") or "unknown"
            )
            similarity_score = InvestigationService._coerce_float(
                supporting_data.get("similarity_score"),
                default=InvestigationService._coerce_float(payload.get("strength")),
            )
            similarity_matches.append(
                {
                    "match_id": str(supporting_data.get("match_id") or ""),
                    "match_type": match_type,
                    "similarity_score": similarity_score,
                    "details": details if isinstance(details, dict) else {},
                    "counter_evidence": supporting_data.get("counter_evidence"),
                }
            )
            normalized_match_type = match_type.lower()
            if normalized_match_type == "vector":
                vector_match_count += 1
            elif normalized_match_type == "attribute":
                attribute_match_count += 1

        sorted_scores = sorted(
            (
                InvestigationService._coerce_float(match.get("similarity_score"))
                for match in similarity_matches
            ),
            reverse=True,
        )
        top_scores = sorted_scores[:5]
        overall_score = sum(top_scores) / len(top_scores) if top_scores else 0.0
        duration_map = stage_durations if isinstance(stage_durations, dict) else {}
        pattern_analysis = {"patterns": patterns}
        similarity_analysis = {
            "matches": similarity_matches,
            "overall_score": round(overall_score, 6),
            "vector_match_count": vector_match_count,
            "attribute_match_count": attribute_match_count,
            "vector_feature_enabled": bool(vector_feature_enabled_default),
            "vector_stage_executed": bool(
                vector_feature_enabled_default and "similarity_analysis" in duration_map
            ),
        }
        return context_snapshot, pattern_analysis, similarity_analysis

    @staticmethod
    def _coerce_bool_map(value: Any) -> dict[str, bool]:
        if not isinstance(value, dict):
            return {}
        parsed: dict[str, bool] = {}
        for key, flag in value.items():
            if isinstance(flag, bool):
                parsed[str(key)] = flag
                continue
            if isinstance(flag, str):
                parsed[str(key)] = flag.strip().lower() in {"1", "true", "yes", "on"}
                continue
            parsed[str(key)] = bool(flag)
        return parsed

    @staticmethod
    def _runtime_feature_flags_snapshot(settings: Any) -> dict[str, bool]:
        return {
            "enable_deterministic_pipeline": bool(settings.features.enable_deterministic_pipeline),
            "enable_llm_reasoning": bool(settings.features.enable_llm_reasoning),
            "vector_search_enabled": bool(settings.vector_search.enabled),
            "counter_evidence_enabled": bool(settings.features.counter_evidence_enabled),
            "conflict_matrix_enabled": bool(settings.features.conflict_matrix_enabled),
            "explanation_builder_enabled": bool(settings.features.explanation_builder_enabled),
            "enable_rule_draft_export": bool(settings.features.enable_rule_draft_export),
            "enforce_human_approval": bool(settings.features.enforce_human_approval),
        }

    @staticmethod
    def _runtime_safeguards_snapshot(
        *, settings: Any, runtime_feature_flags: dict[str, bool]
    ) -> dict[str, bool]:
        vector_enabled = bool(runtime_feature_flags.get("vector_search_enabled", False))
        llm_enabled = bool(runtime_feature_flags.get("enable_llm_reasoning", False))
        return {
            "human_approval_enforced": bool(runtime_feature_flags.get("enforce_human_approval")),
            "prompt_guard_enabled": bool(settings.llm.prompt_guard_enabled),
            "consistency_check_enabled": llm_enabled,
            "vector_fail_closed": vector_enabled,
        }

    @staticmethod
    def _coerce_float(value: Any, default: float = 0.0) -> float:
        try:
            return float(value)
        except TypeError, ValueError:
            return default

    @staticmethod
    def _build_action_plan(
        *,
        recommendations: list[dict[str, Any]],
        evidence: list[dict[str, Any]],
        severity: str,
        llm_status: str,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        return build_action_plan(
            recommendations=recommendations,
            severity=severity,
            llm_status=llm_status,
            evidence=evidence,
        )
