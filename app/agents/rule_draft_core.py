"""Rule draft core - PURE functions for rule draft assembly and validation.

This module contains ZERO database access. Pure functions operating on in-memory data structures.
"""

from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class RuleCondition:
    """Immutable rule condition."""

    field_name: str
    operator: str
    value: Any
    logical_op: str = "AND"


@dataclass(frozen=True)
class RuleDraftPayload:
    """Immutable rule draft payload."""

    rule_name: str
    rule_description: str
    conditions: tuple[RuleCondition, ...]
    thresholds: tuple[tuple[str, Any], ...]
    metadata: tuple[tuple[str, Any], ...]


VALID_OPERATORS = {"=", "!=", ">", "<", ">=", "<=", "IN", "NOT_IN", "BETWEEN", "LIKE"}


def assemble_draft_payload(
    recommendation: dict[str, Any],
    insight: dict[str, Any],
    evidence: list[dict[str, Any]],
) -> RuleDraftPayload:
    """Transform recommendation + evidence into normalized draft.

    Args:
        recommendation: Recommendation dict with type, priority, title, impact
        insight: Insight dict with severity, insight_summary, pattern_scores
        evidence: List of evidence dicts with pattern_name, score, details

    Returns:
        RuleDraftPayload with assembled rule draft data
    """
    rec_type = recommendation.get("type", "")
    payload = recommendation.get("payload", {})
    rec_title = payload.get("title", "") if isinstance(payload, dict) else ""
    rec_impact = payload.get("impact", "") if isinstance(payload, dict) else ""
    insight_summary = insight.get("summary", "")
    severity = insight.get("severity", "MEDIUM")

    conditions = _build_conditions_from_evidence(evidence)
    thresholds = _build_thresholds_from_evidence(evidence)

    rule_name = _generate_rule_name(rec_type, evidence)
    rule_description = _generate_rule_description(
        rec_type, rec_title, rec_impact, insight_summary, severity
    )

    metadata = (
        ("recommendation_id", recommendation.get("recommendation_id")),
        ("insight_id", insight.get("insight_id")),
        ("source", "ops-agent"),
        ("severity", severity),
    )

    return RuleDraftPayload(
        rule_name=rule_name,
        rule_description=rule_description,
        conditions=tuple(conditions),
        thresholds=tuple(thresholds),
        metadata=metadata,
    )


def _build_conditions_from_evidence(evidence: list[dict[str, Any]]) -> list[RuleCondition]:
    """Build rule conditions from evidence.

    Evidence items from DB have structure:
    {
        "evidence_id": "...",
        "evidence_kind": "pattern_velocity",
        "evidence_payload": {"pattern_name": "...", "score": 0.8},
        "created_at": "..."
    }
    """
    conditions = []

    for ev in evidence:
        payload = ev.get("evidence_payload", {})
        pattern_name = payload.get("pattern_name", ev.get("evidence_kind", ""))
        score = payload.get("score", 0)

        if score > 0.5:
            if pattern_name == "velocity" or "velocity" in pattern_name.lower():
                conditions.append(
                    RuleCondition(
                        field_name="transaction_velocity_1h",
                        operator=">",
                        value=5,
                        logical_op="AND",
                    )
                )
            elif pattern_name == "decline_anomaly" or "decline" in pattern_name.lower():
                conditions.append(
                    RuleCondition(
                        field_name="decline_rate_1h",
                        operator=">",
                        value=0.3,
                        logical_op="AND",
                    )
                )
            elif pattern_name == "amount_anomaly" or "amount" in pattern_name.lower():
                conditions.append(
                    RuleCondition(
                        field_name="amount_vs_historical_avg",
                        operator=">",
                        value=3.0,
                        logical_op="AND",
                    )
                )
            elif pattern_name == "geo_improbable" or "geo" in pattern_name.lower():
                conditions.append(
                    RuleCondition(
                        field_name="distance_from_cardholder_location_km",
                        operator=">",
                        value=500,
                        logical_op="AND",
                    )
                )

    return conditions


def _build_thresholds_from_evidence(
    evidence: list[dict[str, Any]],
) -> list[tuple[str, Any]]:
    """Build threshold values from evidence."""
    thresholds = []

    for ev in evidence:
        payload = ev.get("evidence_payload", {})
        pattern_name = payload.get("pattern_name", ev.get("evidence_kind", ""))
        score = payload.get("score", 0)
        thresholds.append((f"{pattern_name}_threshold", round(score, 2)))

    return thresholds


def _generate_rule_name(rec_type: str, evidence: list[dict[str, Any]]) -> str:
    """Generate rule name from recommendation type and evidence."""
    if rec_type == "rule_candidate":
        patterns = []
        for e in evidence:
            payload = e.get("evidence_payload", {})
            if payload.get("score", 0) > 0.5:
                patterns.append(payload.get("pattern_name", e.get("evidence_kind", "unknown")))

        if any("velocity" in p.lower() for p in patterns):
            return "Velocity Threshold Rule - Card Testing Detection"
        elif any("decline" in p.lower() for p in patterns):
            return "Decline Rate Anomaly Rule"
        elif any("amount" in p.lower() for p in patterns):
            return "Amount Deviation Rule"
        elif any("geo" in p.lower() for p in patterns):
            return "Geographic Implausibility Rule"
        return "Ops Agent Generated Rule"
    return "Custom Rule"


def _generate_rule_description(
    rec_type: str,
    rec_title: str,
    rec_impact: str,
    insight_summary: str,
    severity: str,
) -> str:
    """Generate rule description from recommendation data."""
    base_desc = f"Auto-generated rule based on: {insight_summary[:200]}"

    if rec_impact:
        base_desc += f" | Expected impact: {rec_impact}"

    base_desc += f" | Severity: {severity}"

    return base_desc


def validate_draft_payload(payload: RuleDraftPayload) -> list[str]:
    """Validate draft payload.

    Args:
        payload: RuleDraftPayload to validate

    Returns:
        List of validation errors (empty = valid)
    """
    errors = []

    if not payload.rule_name or len(payload.rule_name.strip()) == 0:
        errors.append("rule_name is required")

    if not payload.rule_description or len(payload.rule_description.strip()) == 0:
        errors.append("rule_description is required")

    if len(payload.conditions) == 0:
        errors.append("At least one condition is required")

    for cond in payload.conditions:
        if cond.operator not in VALID_OPERATORS:
            errors.append(f"Invalid operator: {cond.operator} for field {cond.field_name}")

    if payload.rule_name and len(payload.rule_name) > 255:
        errors.append("rule_name must be 255 characters or less")

    return errors
