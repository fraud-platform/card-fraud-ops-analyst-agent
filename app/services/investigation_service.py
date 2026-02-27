"""Investigation service - orchestrates the LangGraph investigation graph."""

from __future__ import annotations

import asyncio
import hashlib
import uuid
from typing import Any

import structlog
from opentelemetry import trace
from sqlalchemy.ext.asyncio import AsyncSession

from app.agent.graph import build_investigation_graph
from app.agent.registry import ToolRegistry
from app.agent.state import create_initial_state
from app.clients.tm_client import TMClient
from app.core.config import get_settings
from app.core.errors import ConflictError, NotFoundError
from app.llm.provider import get_chat_model
from app.persistence.audit_repository import AuditRepository
from app.persistence.insight_repository import InsightRepository
from app.persistence.investigation_repository import InvestigationRepository
from app.persistence.recommendation_repository import RecommendationRepository
from app.persistence.rule_draft_repository import RuleDraftRepository
from app.persistence.state_store import PostgresStateStore
from app.persistence.tool_log_repository import ToolLogRepository
from app.utils.clock import utc_now

logger = structlog.get_logger(__name__)
tracer = trace.get_tracer(__name__)


class InvestigationService:
    """Thin service layer that invokes the LangGraph investigation graph."""

    def __init__(self, session: AsyncSession, settings: Any = None):
        self._session = session
        self._settings = settings or get_settings()
        self._investigation_repo = InvestigationRepository(session)
        self._state_store = PostgresStateStore(session)
        self._tool_log_repo = ToolLogRepository(session)
        self._insight_repo = InsightRepository(session)
        self._recommendation_repo = RecommendationRepository(session)
        self._rule_draft_repo = RuleDraftRepository(session)
        self._audit_repo = AuditRepository(session)
        self._tm_client = TMClient(config=self._settings.tm_client)

    async def run_investigation(
        self,
        transaction_id: str,
        mode: str = "FULL",
    ) -> dict[str, Any]:
        """Run a complete fraud investigation."""
        investigation_id = str(uuid.uuid7())

        existing = await self._investigation_repo.get_active_for_transaction(transaction_id)
        if existing:
            existing_id = str(existing.get("id") or "")
            existing_state = (
                await self._state_store.load_state(existing_id) if existing_id else None
            )
            if existing_id and existing_state is None:
                logger.warning(
                    "Found stale in-progress investigation without state; marking failed",
                    transaction_id=transaction_id,
                    stale_investigation_id=existing_id,
                )
                await self._investigation_repo.update_status(existing_id, "FAILED")
                await self._session.commit()
            else:
                raise ConflictError(
                    f"Investigation already in progress for transaction {transaction_id}",
                    details={"existing_investigation_id": existing["id"]},
                )

        await self._investigation_repo.create(
            investigation_id=investigation_id,
            transaction_id=transaction_id,
            mode=mode,
            planner_model=self._settings.planner.model_name,
            max_steps=self._settings.langgraph.max_steps,
        )
        await self._session.commit()

        await self._audit_repo.emit(
            entity_type="investigation",
            entity_id=investigation_id,
            action="CREATED",
            performed_by="system",
            new_value={"transaction_id": transaction_id, "mode": mode},
        )

        graph = await self._build_graph()

        initial_state = create_initial_state(
            investigation_id=investigation_id,
            transaction_id=transaction_id,
            max_steps=self._settings.langgraph.max_steps,
            feature_flags={
                "planner_llm_enabled": self._settings.planner.llm_enabled,
                "reasoning_llm_enabled": self._settings.features.enable_llm_reasoning,
                "vector_search_enabled": self._settings.vector_search.enabled,
            },
            safeguards={
                "max_steps": self._settings.langgraph.max_steps,
                "investigation_timeout_seconds": (
                    self._settings.langgraph.investigation_timeout_seconds
                ),
                "tool_timeout_seconds": self._settings.langgraph.tool_timeout_seconds,
            },
        )

        await self._investigation_repo.update_status(investigation_id, "IN_PROGRESS")
        await self._session.commit()

        await self._audit_repo.emit(
            entity_type="investigation",
            entity_id=investigation_id,
            action="STARTED",
            performed_by="system",
            new_value={"status": "IN_PROGRESS"},
        )

        try:
            async with asyncio.timeout(self._settings.langgraph.investigation_timeout_seconds):
                with tracer.start_as_current_span("investigation.run") as span:
                    span.set_attribute("investigation_id", investigation_id)
                    span.set_attribute("transaction_id", transaction_id)
                    span.set_attribute("mode", mode)
                    result = await graph.ainvoke(initial_state)
                    span.set_attribute("status", result.get("status", "COMPLETED"))
                    span.set_attribute("severity", result.get("severity", "LOW"))
                    span.set_attribute("step_count", result.get("step_count", 0))
        except TimeoutError:
            result = {
                **initial_state,
                "status": "TIMED_OUT",
                "error": "Investigation timed out",
            }
        except Exception as exc:
            logger.error(
                "Investigation failed with unexpected error",
                investigation_id=investigation_id,
                error=str(exc),
                exc_info=True,
            )
            result = {
                **initial_state,
                "status": "FAILED",
                "error": str(exc),
            }

        await self._complete_investigation(investigation_id, result)

        await self._persist_results(result)
        await self._session.commit()

        await self._audit_repo.emit(
            entity_type="investigation",
            entity_id=investigation_id,
            action="COMPLETED",
            performed_by="system",
            new_value={
                "status": result.get("status", "COMPLETED"),
                "severity": result.get("severity", "LOW"),
                "confidence_score": result.get("confidence_score", 0.0),
                "step_count": result.get("step_count", 0),
            },
        )

        return result

    async def get_investigation(self, investigation_id: str) -> dict[str, Any]:
        """Get full investigation detail."""
        investigation = await self._investigation_repo.get(investigation_id)
        if investigation is None:
            raise NotFoundError(f"Investigation {investigation_id} not found")

        state = await self._state_store.load_state(investigation_id)
        logged_executions = await self._tool_log_repo.get_executions(investigation_id)

        if state is None:
            # State not persisted (e.g. failed before first tool ran).
            # Return a response-compatible dict using DB row fields.
            return self._enrich_detail_response(
                {
                    "investigation_id": investigation.get("id", investigation_id),
                    "transaction_id": investigation.get("transaction_id", ""),
                    "status": investigation.get("status", "UNKNOWN"),
                    "severity": investigation.get("severity", "LOW"),
                    "confidence_score": float(investigation.get("final_confidence") or 0.0),
                    "step_count": investigation.get("step_count", 0),
                    "max_steps": investigation.get("max_steps", 20),
                    "planner_decisions": [],
                    "tool_executions": self._normalize_tool_executions(logged_executions),
                    "recommendations": [],
                    "started_at": str(investigation.get("started_at", "")),
                    "completed_at": investigation.get("completed_at"),
                    "total_duration_ms": None,
                    "context": {},
                    "evidence": [],
                    "pattern_results": {},
                    "similarity_results": {},
                    "reasoning": {},
                    "hypotheses": [],
                    "rule_draft": None,
                }
            )

        merged = {**investigation, **state}
        state_executions = self._normalize_tool_executions(merged.get("tool_executions", []))
        if state_executions and self._has_rich_tool_io(state_executions):
            merged["tool_executions"] = state_executions
            return self._enrich_detail_response(merged)

        logged_normalized = self._normalize_tool_executions(logged_executions)
        if logged_normalized and self._has_rich_tool_io(logged_normalized):
            merged["tool_executions"] = logged_normalized
        else:
            merged["tool_executions"] = state_executions
        return self._enrich_detail_response(merged)

    async def resume_investigation(self, investigation_id: str) -> dict[str, Any]:
        """Resume a failed or interrupted investigation."""
        state = await self._state_store.load_state(investigation_id)
        if state is None:
            raise NotFoundError(f"No state found for investigation {investigation_id}")

        graph = await self._build_graph()

        await self._audit_repo.emit(
            entity_type="investigation",
            entity_id=investigation_id,
            action="RESUMED",
            performed_by="system",
            new_value={"status": "IN_PROGRESS"},
        )

        try:
            async with asyncio.timeout(self._settings.langgraph.investigation_timeout_seconds):
                result = await graph.ainvoke(state)
        except TimeoutError:
            result = {
                **state,
                "status": "TIMED_OUT",
                "error": "Resume timed out",
            }
        except Exception as exc:
            logger.error(
                "Resume failed with unexpected error",
                investigation_id=investigation_id,
                error=str(exc),
                exc_info=True,
            )
            result = {
                **state,
                "status": "FAILED",
                "error": str(exc),
            }

        await self._complete_investigation(investigation_id, result)

        await self._persist_results(result)
        await self._session.commit()

        await self._audit_repo.emit(
            entity_type="investigation",
            entity_id=investigation_id,
            action="COMPLETED",
            performed_by="system",
            new_value={
                "status": result.get("status", "COMPLETED"),
                "severity": result.get("severity", "LOW"),
                "confidence_score": result.get("confidence_score", 0.0),
            },
        )

        return result

    async def _complete_investigation(
        self,
        investigation_id: str,
        result: dict[str, Any],
    ) -> None:
        """Persist the final investigation status with rollback-retry.

        A failed tool's DB call may leave the session in a failed-transaction
        state. We roll back once and retry. If the retry also fails we force
        status=FAILED so the investigation never stays stuck in IN_PROGRESS.
        """
        kwargs = dict(
            investigation_id=investigation_id,
            status=result.get("status", "COMPLETED"),
            severity=result.get("severity", "LOW"),
            final_confidence=result.get("confidence_score", 0.0),
            step_count=result.get("step_count", 0),
        )
        try:
            await self._investigation_repo.complete(**kwargs)
        except Exception as exc:
            logger.warning(
                "complete() failed; rolling back and retrying",
                investigation_id=investigation_id,
                error=str(exc),
            )
            await self._session.rollback()
            try:
                await self._investigation_repo.complete(**kwargs)
            except Exception as exc2:
                logger.error(
                    "complete() failed on retry; marking investigation FAILED",
                    investigation_id=investigation_id,
                    error=str(exc2),
                )
                await self._session.rollback()
                await self._investigation_repo.update_status(
                    investigation_id=investigation_id,
                    status="FAILED",
                )
        await self._session.commit()

    async def _persist_results(self, state: dict[str, Any]) -> None:
        """Persist tool logs, insights, recommendations, and rule drafts after graph completion."""
        investigation_id = state.get("investigation_id", "")
        transaction_id = state.get("transaction_id", "")

        tool_executions = state.get("tool_executions", [])
        for idx, exec_record in enumerate(tool_executions):
            try:
                await self._tool_log_repo.log_execution(
                    investigation_id=investigation_id,
                    tool_name=exec_record.get("tool_name", "unknown"),
                    step_number=idx + 1,
                    input_summary=exec_record.get("input_summary", {}),
                    output_summary=exec_record.get("output_summary", {}),
                    execution_time_ms=exec_record.get("execution_time_ms", 0),
                    status=exec_record.get("status", "SUCCESS"),
                    error_message=exec_record.get("error_message"),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist tool execution log",
                    investigation_id=investigation_id,
                    tool_name=exec_record.get("tool_name"),
                    error=str(exc),
                )

        reasoning = state.get("reasoning", {})
        evidence = state.get("evidence", [])
        severity = state.get("severity", "LOW")
        # Runtime is always agentic; LLM enablement only changes reasoning path within the graph.
        model_mode = "agentic"
        insight_id = ""

        if reasoning or evidence:
            try:
                summary = self._build_insight_summary(reasoning, evidence)
                if not summary and evidence:
                    summary = f"Found {len(evidence)} pieces of evidence"

                idempotency_key = self._compute_insight_key(
                    transaction_id=transaction_id,
                    insight_type="agentic_investigation",
                    model_mode=model_mode,
                )

                insight = await self._insight_repo.upsert_insight(
                    transaction_id=transaction_id,
                    severity=severity,
                    summary=summary,
                    insight_type="agentic_investigation",
                    model_mode=model_mode,
                    idempotency_key=idempotency_key,
                )

                insight_id = insight.get("insight_id", "")
                for ev in evidence:
                    try:
                        evidence_kind, evidence_payload = self._normalize_evidence_item(ev)
                        await self._insight_repo.add_evidence(
                            insight_id=insight_id,
                            evidence_kind=evidence_kind,
                            evidence_payload=evidence_payload,
                        )
                    except Exception as exc:
                        logger.warning(
                            "Failed to add evidence to insight",
                            insight_id=insight_id,
                            error=str(exc),
                        )
            except Exception as exc:
                logger.warning(
                    "Failed to persist insight",
                    investigation_id=investigation_id,
                    error=str(exc),
                )

        recommendations = state.get("recommendations", [])
        for rec in recommendations:
            try:
                rec_type = rec.get("type", "REVIEW")
                rec_payload = rec.get("payload", {})
                rec_title = rec.get("title", "Generated recommendation")
                rec_impact = rec.get("impact", "Review recommended")

                idempotency_key = self._compute_recommendation_key(
                    investigation_id=investigation_id,
                    rec_type=rec_type,
                    payload_hash=hashlib.sha256(str(rec_payload).encode()).hexdigest()[:16],
                )

                await self._recommendation_repo.upsert_recommendation(
                    insight_id=insight_id,
                    recommendation_type=rec_type,
                    payload=rec_payload,
                    idempotency_key=idempotency_key,
                    title=rec_title,
                    impact=rec_impact,
                    investigation_id=investigation_id,
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist recommendation",
                    investigation_id=investigation_id,
                    error=str(exc),
                )

        rule_draft = state.get("rule_draft")
        if rule_draft:
            try:
                await self._rule_draft_repo.create(
                    investigation_id=investigation_id,
                    rule_name=rule_draft.get("rule_name", "Draft Rule"),
                    rule_description=rule_draft.get("rule_description", ""),
                    conditions=rule_draft.get("conditions", []),
                    thresholds=rule_draft.get("thresholds", {}),
                    metadata=rule_draft.get("metadata"),
                    recommendation_id=rule_draft.get("recommendation_id"),
                )
            except Exception as exc:
                logger.warning(
                    "Failed to persist rule draft",
                    investigation_id=investigation_id,
                    error=str(exc),
                )

    @staticmethod
    def _build_insight_summary(reasoning: Any, evidence: list[Any]) -> str:
        """Build stable summary text from current agentic reasoning/evidence shapes."""
        reasoning_dict = reasoning if isinstance(reasoning, dict) else {}
        for key in ("summary", "narrative"):
            value = reasoning_dict.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
        findings = reasoning_dict.get("key_findings")
        if isinstance(findings, list):
            rendered = [str(item).strip() for item in findings if str(item).strip()]
            if rendered:
                return "; ".join(rendered[:3])
        if evidence:
            return f"Found {len(evidence)} pieces of evidence"
        return "Investigation completed"

    @staticmethod
    def _normalize_evidence_item(evidence_item: Any) -> tuple[str, dict[str, Any]]:
        """Normalize mixed evidence shapes into repository contract."""
        if not isinstance(evidence_item, dict):
            return "unknown", {}

        evidence_kind = str(
            evidence_item.get("kind")
            or evidence_item.get("evidence_kind")
            or evidence_item.get("category")
            or evidence_item.get("tool")
            or "unknown"
        )

        payload = evidence_item.get("payload")
        if not isinstance(payload, dict):
            payload = {}

        supporting = evidence_item.get("data")
        if isinstance(supporting, dict) and supporting:
            payload = {**payload, "supporting_data": supporting}

        for key in ("category", "description", "tool"):
            value = evidence_item.get(key)
            if value is not None and key not in payload:
                payload[key] = value

        return evidence_kind, payload

    @staticmethod
    def _compute_insight_key(
        transaction_id: str,
        insight_type: str,
        model_mode: str,
    ) -> str:
        """Compute idempotency key for insight."""
        now = utc_now()
        components = [
            str(transaction_id),
            str(insight_type),
            str(model_mode),
            now.strftime("%Y-%m-%d"),
        ]
        raw = "|".join(components)
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _compute_recommendation_key(
        investigation_id: str,
        rec_type: str,
        payload_hash: str,
    ) -> str:
        """Compute idempotency key for recommendation."""
        components = [str(investigation_id), str(rec_type), str(payload_hash)]
        raw = "|".join(components)
        return hashlib.sha256(raw.encode()).hexdigest()

    @staticmethod
    def _normalize_tool_executions(executions: Any) -> list[dict[str, Any]]:
        normalized: list[dict[str, Any]] = []
        if not isinstance(executions, list):
            return normalized
        for item in executions:
            if not isinstance(item, dict):
                continue
            normalized.append(
                {
                    "tool_name": item.get("tool_name", "unknown"),
                    "input_summary": item.get("input_summary")
                    if isinstance(item.get("input_summary"), dict)
                    else {},
                    "output_summary": item.get("output_summary")
                    if isinstance(item.get("output_summary"), dict)
                    else {},
                    "execution_time_ms": int(item.get("execution_time_ms", 0) or 0),
                    "status": item.get("status", "UNKNOWN"),
                    "error_message": item.get("error_message"),
                    "timestamp": item.get("timestamp") or item.get("created_at") or "",
                }
            )
        return normalized

    @staticmethod
    def _has_rich_tool_io(executions: list[dict[str, Any]]) -> bool:
        if not executions:
            return False
        for item in executions:
            input_summary = item.get("input_summary")
            output_summary = item.get("output_summary")
            if isinstance(input_summary, dict) and isinstance(output_summary, dict):
                if input_summary or output_summary:
                    return True
        return False

    async def _build_graph(self):
        """Build the investigation graph with all dependencies."""
        from app.clients.embedding_client import EmbeddingClient

        llm = get_chat_model(self._settings)
        registry = ToolRegistry()

        from app.tools.context_tool import ContextTool
        from app.tools.pattern_tool import PatternTool
        from app.tools.reasoning_tool import ReasoningTool
        from app.tools.recommendation_tool import RecommendationTool
        from app.tools.rule_draft_tool import RuleDraftTool
        from app.tools.similarity_tool import SimilarityTool

        registry.register(ContextTool(tm_client=self._tm_client))
        registry.register(PatternTool())
        registry.register(
            SimilarityTool(
                embedding_client=EmbeddingClient(self._settings),
                session=self._session,
            )
        )
        registry.register(ReasoningTool(llm=llm, settings=self._settings))
        registry.register(RecommendationTool())
        registry.register(RuleDraftTool())

        return build_investigation_graph(
            registry=registry,
            llm=llm,
            settings=self._settings,
            state_store=self._state_store,
        )

    def _enrich_detail_response(self, payload: dict[str, Any]) -> dict[str, Any]:
        """Backfill stable API fields used by E2E and downstream report tooling."""
        response = dict(payload)
        response["model_mode"] = str(response.get("model_mode") or "agentic")
        raw_hypotheses = response.get("hypotheses")
        response["hypothesis_details"] = self._normalize_hypothesis_details(raw_hypotheses)
        response["hypotheses"] = self._normalize_hypotheses(raw_hypotheses)

        insight = response.get("insight")
        insight_dict = insight if isinstance(insight, dict) else {}
        severity = str(insight_dict.get("severity") or response.get("severity") or "LOW")

        summary = insight_dict.get("summary")
        if not isinstance(summary, str) or not summary.strip():
            reasoning = response.get("reasoning")
            reasoning_dict = reasoning if isinstance(reasoning, dict) else {}
            evidence = response.get("evidence")
            evidence_list = evidence if isinstance(evidence, list) else []
            summary = self._build_insight_summary(reasoning_dict, evidence_list)

        response["insight"] = {"severity": severity, "summary": summary}
        return response

    @staticmethod
    def _normalize_hypotheses(raw: Any) -> list[str]:
        """Normalize mixed hypothesis payloads to API schema list[str]."""
        if not isinstance(raw, list):
            return []

        normalized: list[str] = []
        for item in raw:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    normalized.append(text)
                continue

            if isinstance(item, dict):
                text = str(item.get("hypothesis") or item.get("text") or "").strip()
                if text:
                    normalized.append(text)
        return normalized

    @staticmethod
    def _normalize_hypothesis_details(raw: Any) -> list[dict[str, Any]]:
        """Normalize mixed hypotheses into structured details for agentic consumers."""
        if not isinstance(raw, list):
            return []

        details: list[dict[str, Any]] = []
        for item in raw:
            if isinstance(item, str):
                text = item.strip()
                if text:
                    details.append(
                        {
                            "hypothesis": text,
                            "supporting_evidence": [],
                            "contradicting_evidence": [],
                        }
                    )
                continue

            if not isinstance(item, dict):
                continue

            text = str(item.get("hypothesis") or item.get("text") or "").strip()
            if not text:
                continue

            detail: dict[str, Any] = {
                "hypothesis": text,
                "supporting_evidence": [],
                "contradicting_evidence": [],
            }

            confidence = item.get("confidence")
            if confidence is not None:
                try:
                    detail["confidence"] = max(0.0, min(1.0, float(confidence)))
                except TypeError, ValueError:
                    pass

            for key in ("supporting_evidence", "contradicting_evidence"):
                values = item.get(key)
                if isinstance(values, list):
                    detail[key] = [
                        str(value).strip()[:200] for value in values if str(value).strip()
                    ][:10]

            details.append(detail)

        return details

    async def close(self) -> None:
        """Close resources."""
        await self._tm_client.close()
