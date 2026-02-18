"""Shared action-plan generation for investigation responses."""

from __future__ import annotations

from typing import Any

from app.agents.pattern_utils import to_pattern_dicts
from app.agents.similarity_utils import get_similarity_score


def build_action_plan(
    *,
    recommendations: list[dict[str, Any]],
    severity: str,
    llm_status: str,
    context: dict[str, Any] | None = None,
    pattern_analysis: dict[str, Any] | None = None,
    similarity_analysis: dict[str, Any] | None = None,
    evidence: list[dict[str, Any]] | None = None,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Generate next-best actions and explicit evidence gaps."""
    actions: list[dict[str, Any]] = []
    seen_actions: set[str] = set()

    def append_action(
        priority: int, action: str, rationale: str, evidence_ref: str | None = None
    ) -> None:
        key = action.strip().lower()
        if not key or key in seen_actions:
            return
        seen_actions.add(key)
        actions.append(
            {
                "priority": priority,
                "action": action,
                "rationale": rationale,
                "evidence_ref": evidence_ref,
                "owner": "fraud_analyst",
            }
        )

    for rec in recommendations:
        if not isinstance(rec, dict):
            continue
        payload = rec.get("payload") if isinstance(rec.get("payload"), dict) else {}
        title = str(payload.get("title", "")).strip()
        impact = str(payload.get("impact", "")).strip()
        rec_type = str(rec.get("type") or rec.get("recommendation_type") or "recommendation")
        if title:
            append_action(
                priority=int(rec.get("priority") or 3),
                action=title,
                rationale=impact or "Follow generated recommendation.",
                evidence_ref=f"recommendation:{rec_type}",
            )

    pattern_details = {
        str(p.get("pattern_name", "")): p
        for p in to_pattern_dicts(pattern_analysis or {})
        if isinstance(p, dict)
    }
    velocity_score = float((pattern_details.get("velocity") or {}).get("score", 0.0))
    decline_score = float((pattern_details.get("decline_anomaly") or {}).get("score", 0.0))
    cross_score = float((pattern_details.get("cross_merchant") or {}).get("score", 0.0))
    time_score = float((pattern_details.get("time_anomaly") or {}).get("score", 0.0))
    similarity_score = get_similarity_score(similarity_analysis or {})

    vector_match_count = 0
    if isinstance(similarity_analysis, dict):
        vector_match_count = int(similarity_analysis.get("vector_match_count") or 0)
    if vector_match_count == 0 and isinstance(evidence, list):
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
                vector_match_count += 1
                continue
            metadata = payload.get("metadata") if isinstance(payload.get("metadata"), dict) else {}
            if str(metadata.get("source", "")).lower() == "vector":
                vector_match_count += 1

    if severity in {"CRITICAL", "HIGH"}:
        append_action(
            priority=1,
            action="Escalate to L2 fraud review queue",
            rationale=f"Severity {severity} requires immediate analyst disposition and documented rationale.",
            evidence_ref="severity",
        )
    if velocity_score >= 0.6:
        append_action(
            priority=1,
            action="Review rapid-velocity authorization chain",
            rationale=f"Velocity score {velocity_score:.2f} indicates burst transaction behavior.",
            evidence_ref="pattern:velocity",
        )
    if decline_score >= 0.5:
        append_action(
            priority=2,
            action="Request issuer decline-reason breakdown",
            rationale=f"Decline anomaly score {decline_score:.2f} suggests coordinated retries.",
            evidence_ref="pattern:decline_anomaly",
        )
    if cross_score >= 0.5:
        append_action(
            priority=2,
            action="Investigate cross-merchant spread for card token",
            rationale=f"Cross-merchant score {cross_score:.2f} indicates possible distributed testing.",
            evidence_ref="pattern:cross_merchant",
        )
    if time_score >= 0.5:
        append_action(
            priority=3,
            action="Validate temporal anomalies against customer profile",
            rationale=f"Time anomaly score {time_score:.2f} may indicate out-of-pattern usage.",
            evidence_ref="pattern:time_anomaly",
        )
    if similarity_score >= 0.5:
        append_action(
            priority=2,
            action="Review top similarity matches for linked fraud signals",
            rationale=f"Similarity score {similarity_score:.2f} with {vector_match_count} vector matches.",
            evidence_ref="similarity",
        )

    evidence_gaps: list[str] = []
    if isinstance(context, dict) and context:
        tx_context = context.get("transaction_context") if isinstance(context, dict) else {}
        velocity_snapshot = context.get("velocity_snapshot") if isinstance(context, dict) else None
        card_history = context.get("card_history") if isinstance(context, dict) else None

        if not isinstance(velocity_snapshot, dict) or not velocity_snapshot:
            evidence_gaps.append("Velocity snapshot unavailable for full behavioral baseline.")
        if not isinstance(card_history, list) or len(card_history) == 0:
            evidence_gaps.append("Card history is limited; sequence confidence may be reduced.")
        if not isinstance(tx_context, dict):
            tx_context = {}
        if "3ds_verified" not in tx_context and "three_ds_authenticated" not in tx_context:
            evidence_gaps.append("3DS authentication signal missing in transaction context.")
        if "device_trusted" not in tx_context and "is_trusted_device" not in tx_context:
            evidence_gaps.append("Device trust telemetry missing for this transaction.")
    elif not evidence:
        evidence_gaps.append("No structured evidence envelope found for this run.")

    if llm_status in {"fallback", "failed"}:
        evidence_gaps.append("LLM reasoning fallback executed; deterministic narrative used.")
    vector_stage_executed = (
        bool(similarity_analysis.get("vector_stage_executed")) if similarity_analysis else False
    )
    if vector_stage_executed and vector_match_count == 0:
        evidence_gaps.append("Vector search returned no close historical matches in active window.")

    if evidence_gaps:
        append_action(
            priority=2,
            action="Collect missing telemetry before final disposition",
            rationale=evidence_gaps[0],
            evidence_ref="data_quality",
        )

    actions.sort(key=lambda item: int(item.get("priority", 9)))
    return actions[:8], evidence_gaps[:8]
