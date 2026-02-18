"""Unit tests for rule draft core (pure functions)."""

import json

from app.agents.rule_draft_core import (
    RuleCondition,
    RuleDraftPayload,
    _build_conditions_from_evidence,
    _build_thresholds_from_evidence,
    _generate_rule_description,
    _generate_rule_name,
    assemble_draft_payload,
    validate_draft_payload,
)


def test_assemble_draft_payload_velocity_pattern():
    """Test assembling draft payload with velocity evidence."""
    recommendation = {
        "recommendation_id": "rec-1",
        "type": "rule_candidate",
        "payload": {
            "title": "High Velocity Burst",
            "impact": "Reduce false positives by 15%",
        },
    }

    insight = {
        "insight_id": "insight-1",
        "severity": "HIGH",
        "summary": "Unusual cross-merchant burst with elevated decline ratio",
    }

    evidence = [
        {
            "evidence_id": "ev-1",
            "evidence_kind": "pattern_velocity",
            "evidence_payload": {
                "pattern_name": "velocity",
                "score": 0.85,
            },
        },
    ]

    result = assemble_draft_payload(recommendation, insight, evidence)

    print("\n[RULE_DRAFT_CORE] Input:")
    print(f"  recommendation: {json.dumps(recommendation, indent=2)}")
    print(f"  insight: {json.dumps(insight, indent=2)}")
    print(f"  evidence: {json.dumps(evidence, indent=2)}")
    print("[RULE_DRAFT_CORE] Output:")
    print(f"  rule_name: {result.rule_name}")
    print(f"  rule_description: {result.rule_description}")
    print(f"  conditions: {len(result.conditions)} conditions")
    print(f"  thresholds: {len(result.thresholds)} thresholds")
    print(f"  metadata: {len(result.metadata)} metadata items")

    assert result.rule_name == "Velocity Threshold Rule - Card Testing Detection"
    assert len(result.conditions) == 1
    assert result.conditions[0].field_name == "transaction_velocity_1h"
    assert result.conditions[0].operator == ">"
    assert result.conditions[0].value == 5
    assert len(result.thresholds) == 1


def test_assemble_draft_payload_decline_pattern():
    """Test assembling draft payload with decline anomaly evidence."""
    recommendation = {
        "recommendation_id": "rec-2",
        "type": "rule_candidate",
        "payload": {
            "title": "Decline Rate Anomaly",
            "impact": "Catch fraud rings faster",
        },
    }

    insight = {
        "insight_id": "insight-2",
        "severity": "CRITICAL",
        "summary": "High decline rate pattern detected",
    }

    evidence = [
        {
            "evidence_id": "ev-2",
            "evidence_kind": "pattern_decline_anomaly",
            "evidence_payload": {
                "pattern_name": "decline_anomaly",
                "score": 0.92,
            },
        },
    ]

    result = assemble_draft_payload(recommendation, insight, evidence)

    print("\n[RULE_DRAFT_CORE] Input:")
    print(f"  recommendation type: {recommendation['type']}")
    print(f"  insight severity: {insight['severity']}")
    print(f"  evidence pattern: {evidence[0]['evidence_payload']['pattern_name']}")
    print("[RULE_DRAFT_CORE] Output:")
    print(f"  rule_name: {result.rule_name}")
    print(
        f"  conditions: {result.conditions[0].field_name} {result.conditions[0].operator} {result.conditions[0].value}"
    )

    assert result.rule_name == "Decline Rate Anomaly Rule"
    assert result.conditions[0].field_name == "decline_rate_1h"
    assert result.conditions[0].value == 0.3


def test_assemble_draft_payload_multiple_evidence():
    """Test assembling draft with multiple evidence items."""
    recommendation = {
        "recommendation_id": "rec-3",
        "type": "rule_candidate",
        "payload": {"title": "Multi-pattern Fraud", "impact": "High"},
    }

    insight = {
        "insight_id": "insight-3",
        "severity": "CRITICAL",
        "summary": "Multiple fraud indicators detected",
    }

    evidence = [
        {
            "evidence_id": "ev-3a",
            "evidence_kind": "pattern_velocity",
            "evidence_payload": {"pattern_name": "velocity", "score": 0.9},
        },
        {
            "evidence_id": "ev-3b",
            "evidence_kind": "pattern_decline_anomaly",
            "evidence_payload": {"pattern_name": "decline_anomaly", "score": 0.8},
        },
    ]

    result = assemble_draft_payload(recommendation, insight, evidence)

    print("\n[RULE_DRAFT_CORE] Input with multiple evidence items:")
    print(f"  evidence count: {len(evidence)}")
    print("[RULE_DRAFT_CORE] Output:")
    print(f"  conditions generated: {len(result.conditions)}")
    print(f"  thresholds generated: {len(result.thresholds)}")

    assert len(result.conditions) == 2
    assert len(result.thresholds) == 2
    assert result.metadata[3] == ("severity", "CRITICAL")


def test_build_conditions_from_evidence_low_score():
    """Test that low-score evidence doesn't generate conditions."""
    evidence = [
        {
            "evidence_id": "ev-low",
            "evidence_kind": "pattern_velocity",
            "evidence_payload": {"pattern_name": "velocity", "score": 0.3},
        },
    ]

    conditions = _build_conditions_from_evidence(evidence)

    print("\n[RULE_DRAFT_CORE] Low-score evidence:")
    print("  score: 0.3")
    print(f"  conditions generated: {len(conditions)}")

    assert len(conditions) == 0


def test_build_conditions_from_evidence_all_patterns():
    """Test building conditions for all pattern types."""
    evidence = [
        {
            "evidence_id": "ev-geo",
            "evidence_kind": "pattern_geo",
            "evidence_payload": {"pattern_name": "geo_improbable", "score": 0.8},
        },
        {
            "evidence_id": "ev-amount",
            "evidence_kind": "pattern_amount",
            "evidence_payload": {"pattern_name": "amount_anomaly", "score": 0.9},
        },
    ]

    conditions = _build_conditions_from_evidence(evidence)

    print("\n[RULE_DRAFT_CORE] All pattern types:")
    print(f"  evidence count: {len(evidence)}")
    print(f"  conditions generated: {len(conditions)}")
    print(f"  fields: {[c.field_name for c in conditions]}")

    assert len(conditions) == 2
    assert any(c.field_name == "distance_from_cardholder_location_km" for c in conditions)
    assert any(c.field_name == "amount_vs_historical_avg" for c in conditions)


def test_build_thresholds_from_evidence():
    """Test building thresholds from evidence."""
    evidence = [
        {
            "evidence_id": "ev-1",
            "evidence_kind": "pattern_velocity",
            "evidence_payload": {"pattern_name": "velocity", "score": 0.856},
        },
        {
            "evidence_id": "ev-2",
            "evidence_kind": "pattern_decline",
            "evidence_payload": {"pattern_name": "decline_anomaly", "score": 0.923},
        },
    ]

    thresholds = _build_thresholds_from_evidence(evidence)

    print("\n[RULE_DRAFT_CORE] Thresholds:")
    print(f"  thresholds: {thresholds}")

    assert len(thresholds) == 2
    assert thresholds[0] == ("velocity_threshold", 0.86)
    assert thresholds[1] == ("decline_anomaly_threshold", 0.92)


def test_generate_rule_name_velocity():
    """Test rule name generation for velocity patterns."""
    evidence = [{"evidence_payload": {"pattern_name": "velocity_burst", "score": 0.9}}]

    name = _generate_rule_name("rule_candidate", evidence)

    print("\n[RULE_DRAFT_CORE] Rule name for velocity:")
    print(f"  {name}")

    assert "Velocity" in name


def test_generate_rule_name_custom():
    """Test rule name for non-rule_candidate types."""
    name = _generate_rule_name("manual_review", [])

    print("\n[RULE_DRAFT_CORE] Rule name for custom type:")
    print(f"  {name}")

    assert name == "Custom Rule"


def test_generate_rule_description():
    """Test rule description generation."""
    description = _generate_rule_description(
        rec_type="rule_candidate",
        rec_title="High Velocity Alert",
        rec_impact="Reduces fraud losses by 10%",
        insight_summary="Unusual velocity pattern detected on card ending in 1234",
        severity="HIGH",
    )

    print("\n[RULE_DRAFT_CORE] Rule description:")
    print(f"  {description}")

    assert "velocity pattern" in description.lower()
    assert "Reduces fraud losses by 10%" in description
    assert "HIGH" in description


def test_validate_draft_payload_valid():
    """Test validation of valid payload."""
    payload = RuleDraftPayload(
        rule_name="Valid Rule",
        rule_description="A valid rule description",
        conditions=(RuleCondition(field_name="amount", operator=">", value=100),),
        thresholds=(("min_amount", 100),),
        metadata=(("source", "ops-agent"),),
    )

    errors = validate_draft_payload(payload)

    print("\n[RULE_DRAFT_CORE] Validation of valid payload:")
    print(f"  errors: {errors}")

    assert len(errors) == 0


def test_validate_draft_payload_empty_name():
    """Test validation detects empty rule name."""
    payload = RuleDraftPayload(
        rule_name="",
        rule_description="Valid description",
        conditions=(RuleCondition(field_name="amount", operator=">", value=100),),
        thresholds=(),
        metadata=(),
    )

    errors = validate_draft_payload(payload)

    print("\n[RULE_DRAFT_CORE] Validation errors:")
    print(f"  {errors}")

    assert "rule_name is required" in errors


def test_validate_draft_payload_no_conditions():
    """Test validation detects missing conditions."""
    payload = RuleDraftPayload(
        rule_name="Valid Name",
        rule_description="Valid description",
        conditions=(),
        thresholds=(),
        metadata=(),
    )

    errors = validate_draft_payload(payload)

    print("\n[RULE_DRAFT_CORE] Validation for missing conditions:")
    print(f"  {errors}")

    assert "At least one condition is required" in errors


def test_validate_draft_payload_invalid_operator():
    """Test validation detects invalid operator."""
    payload = RuleDraftPayload(
        rule_name="Valid Name",
        rule_description="Valid description",
        conditions=(RuleCondition(field_name="amount", operator="INVALID", value=100),),
        thresholds=(),
        metadata=(),
    )

    errors = validate_draft_payload(payload)

    print("\n[RULE_DRAFT_CORE] Validation for invalid operator:")
    print(f"  {errors}")

    assert "Invalid operator: INVALID" in errors[0]


def test_validate_draft_payload_name_too_long():
    """Test validation detects rule name too long."""
    payload = RuleDraftPayload(
        rule_name="x" * 256,  # Exceeds 255 char limit
        rule_description="Valid description",
        conditions=(RuleCondition(field_name="amount", operator=">", value=100),),
        thresholds=(),
        metadata=(),
    )

    errors = validate_draft_payload(payload)

    print("\n[RULE_DRAFT_CORE] Validation for name too long:")
    print(f"  {errors}")

    assert "255 characters or less" in errors[0]


def test_assemble_draft_payload_metadata():
    """Test that metadata includes all expected fields."""
    recommendation = {
        "recommendation_id": "rec-meta",
        "type": "rule_candidate",
        "payload": {"title": "Test", "impact": "Test impact"},
    }

    insight = {
        "insight_id": "insight-meta",
        "severity": "MEDIUM",
        "summary": "Test summary",
    }

    result = assemble_draft_payload(recommendation, insight, [])

    print("\n[RULE_DRAFT_CORE] Metadata fields:")
    for key, value in result.metadata:
        print(f"  {key}: {value}")

    assert result.metadata[0] == ("recommendation_id", "rec-meta")
    assert result.metadata[1] == ("insight_id", "insight-meta")
    assert result.metadata[2] == ("source", "ops-agent")
    assert result.metadata[3] == ("severity", "MEDIUM")
