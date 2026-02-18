"""Reasoning engine core - PURE functions for LLM reasoning preparation.

This module contains ZERO database access. Pure functions operating on in-memory data.
"""

import dataclasses
import json
from typing import Any

from app.agents.pattern_utils import to_pattern_dicts


def _similarity_dict(similarity_analysis: dict[str, Any]) -> dict[str, Any]:
    sim_result = similarity_analysis.get("similarity_result")
    if sim_result is not None:
        matches = [
            {
                "transaction_id": getattr(m, "match_id", ""),
                "match_type": getattr(m, "match_type", "unknown"),
                "score": float(getattr(m, "similarity_score", 0.0)),
                "details": getattr(m, "details", {}) or {},
                "counter_evidence": getattr(m, "counter_evidence", None),
            }
            for m in getattr(sim_result, "matches", [])
        ]
        return {
            "overall_score": float(getattr(sim_result, "overall_score", 0.0)),
            "matches": matches,
            "counter_evidence": getattr(sim_result, "counter_evidence", None),
        }

    similar_transactions = similarity_analysis.get("similar_transactions") or []
    overall_score = float(similarity_analysis.get("overall_score", 0.0))
    return {
        "overall_score": overall_score,
        "matches": similar_transactions if isinstance(similar_transactions, list) else [],
        "counter_evidence": similarity_analysis.get("counter_evidence"),
    }


def _observation_lines(context: dict[str, Any]) -> list[str]:
    observations: list[str] = []
    for signal in context.get("signals", []):
        name = getattr(signal, "name", None) or (
            signal.get("name") if isinstance(signal, dict) else None
        )
        value = (
            getattr(signal, "value", None) if not isinstance(signal, dict) else signal.get("value")
        )
        if name:
            observations.append(f"{name}: {value}")
    return observations[:20]


def assemble_prompt_payload(
    context: dict[str, Any],
    pattern_analysis: dict[str, Any],
    similarity_analysis: dict[str, Any],
    conflict_matrix: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Assemble structured evidence for prompt template.

    Args:
        context: Transaction context data
        pattern_analysis: Pattern scoring results
        similarity_analysis: Similarity analysis results

    Returns:
        Dict with formatted evidence for LLM prompt
    """
    transaction = context.get("transaction")
    # Convert dataclass to dict if needed
    if dataclasses.is_dataclass(transaction) and not isinstance(transaction, type):
        transaction = dataclasses.asdict(transaction)
    transaction = transaction or {}

    pattern_lines = []
    for pattern in to_pattern_dicts(pattern_analysis):
        name = pattern.get("pattern_name", "unknown")
        score = pattern.get("score", 0)
        details = pattern.get("details", {})

        detail_desc = []
        if name == "velocity" and "burst_1h" in details:
            count = details["burst_1h"]
            detail_desc.append(f"{count} transactions in 1 hour")
        if name == "velocity" and "burst_6h" in details:
            count = details["burst_6h"]
            detail_desc.append(f"{count} transactions in 6 hours")
        if name == "decline_anomaly" and "decline_ratio_24h" in details:
            ratio = details["decline_ratio_24h"]
            pct = ratio * 100
            detail_desc.append(f"{pct:.0f}% decline rate in 24h")
        if name == "cross_merchant" and "unique_merchants_24h" in details:
            count = details["unique_merchants_24h"]
            detail_desc.append(f"{count} unique merchants in 24h")
        if name == "amount_anomaly":
            if details.get("round_number"):
                detail_desc.append(f"round number (${details.get('amount')})")
            if details.get("high_amount"):
                detail_desc.append(f"high amount (${details.get('high_amount')})")
            if details.get("elevated_amount"):
                detail_desc.append(f"elevated amount (${details.get('elevated_amount')})")
            if details.get("outlier"):
                z = details.get("z_score")
                detail_desc.append(f"statistical outlier (z-score: {z})")
            if details.get("spike_vs_avg"):
                detail_desc.append(f"{details.get('spike_vs_avg')}x spike vs average")
        if name == "time_anomaly":
            if details.get("unusual_hour") is not None:
                detail_desc.append(f"unusual hour ({details.get('unusual_hour')}:00)")
            if details.get("timezone_mismatch"):
                ip = details.get("ip_country", "?")
                card = details.get("card_country", "?")
                detail_desc.append(f"timezone mismatch ({ip} vs {card})")
            if details.get("high_risk_combo"):
                detail_desc.append("high-risk merchant + unusual hour")
            if details.get("unusual_hour_for_cardholder"):
                usual = details.get("usual_hours", [])
                detail_desc.append(f"first transaction at unusual hour (usual: {usual})")

        if detail_desc:
            pattern_lines.append(f"  - {name}: {score:.2f} - {', '.join(detail_desc)}")
        else:
            detail_parts = []
            for key, value in details.items():
                if isinstance(value, (int, float)):
                    detail_parts.append(f"{key}={value}")
            if detail_parts:
                pattern_lines.append(f"  - {name}: {score:.2f} ({', '.join(detail_parts)})")
            else:
                pattern_lines.append(f"  - {name}: {score:.2f}")

    similarity_summary = _similarity_dict(similarity_analysis)
    similarity_data = similarity_summary.get("matches", [])
    if similarity_data:
        sim_lines = [
            f"  - {s.get('transaction_id', '?')}: score {s.get('score', s.get('similarity_score', 0)):.2f}"
            for s in similarity_data[:5]
        ]
    else:
        sim_lines = ["  - No similar transactions found"]

    velocity = context.get("velocity_snapshot") or {}
    if dataclasses.is_dataclass(velocity) and not isinstance(velocity, type):
        velocity = dataclasses.asdict(velocity)
    velocity = velocity if isinstance(velocity, dict) else {}

    tx_context = context.get("transaction_context") or {}
    if dataclasses.is_dataclass(tx_context) and not isinstance(tx_context, type):
        tx_context = dataclasses.asdict(tx_context)
    tx_context = tx_context if isinstance(tx_context, dict) else {}

    context_counter_evidence: list[str] = []
    if tx_context.get("3ds_verified") is True:
        context_counter_evidence.append("3DS verified")
    if tx_context.get("device_trusted") is True:
        context_counter_evidence.append("trusted device")
    if tx_context.get("cardholder_present") is True:
        context_counter_evidence.append("cardholder present")
    if tx_context.get("is_recurring_customer") is True:
        context_counter_evidence.append("recurring customer")
    if tx_context.get("avs_match") is True or tx_context.get("avs_response") == "Y":
        context_counter_evidence.append("AVS matched")
    if tx_context.get("cvv_match") is True or tx_context.get("cvv_response") == "Y":
        context_counter_evidence.append("CVV verified")
    if tx_context.get("is_tokenized") is True or tx_context.get("payment_token_present") is True:
        context_counter_evidence.append("tokenized payment")
    if tx_context.get("is_known_merchant") is True:
        context_counter_evidence.append("known merchant")

    counter_evidence_text = "None detected"
    counter_evidence = similarity_summary.get("counter_evidence")
    if counter_evidence:
        counter_evidence_text = json.dumps(counter_evidence)
        if context_counter_evidence:
            counter_summary = ", ".join(context_counter_evidence)
            counter_evidence_text = f"{counter_evidence_text}; context={counter_summary}"
    elif context_counter_evidence:
        counter_evidence_text = ", ".join(context_counter_evidence)

    three_ds_authenticated = transaction.get("three_ds_authenticated")
    if three_ds_authenticated is None:
        three_ds_authenticated = transaction.get("3ds_verified")
    if three_ds_authenticated is None and "3ds_verified" in tx_context:
        three_ds_authenticated = tx_context.get("3ds_verified")
    if three_ds_authenticated is None:
        three_ds_authenticated = "unknown"

    device_trusted = transaction.get("device_trusted")
    if device_trusted is None and "device_trusted" in tx_context:
        device_trusted = tx_context.get("device_trusted")
    if device_trusted is None:
        device_trusted = "unknown"

    avs_match = transaction.get("avs_match")
    if avs_match is None:
        avs_match = transaction.get("avs_response")
    if avs_match is None and "avs_match" in tx_context:
        avs_match = tx_context.get("avs_match")
    if avs_match is None and "avs_response" in tx_context:
        avs_match = tx_context.get("avs_response")
    if avs_match is None:
        avs_match = "unknown"

    cvv_match = transaction.get("cvv_match")
    if cvv_match is None:
        cvv_match = transaction.get("cvv_response")
    if cvv_match is None and "cvv_match" in tx_context:
        cvv_match = tx_context.get("cvv_match")
    if cvv_match is None and "cvv_response" in tx_context:
        cvv_match = tx_context.get("cvv_response")
    if cvv_match is None:
        cvv_match = "unknown"

    is_tokenized = transaction.get("is_tokenized")
    if is_tokenized is None:
        is_tokenized = transaction.get("payment_token_present")
    if is_tokenized is None and "is_tokenized" in tx_context:
        is_tokenized = tx_context.get("is_tokenized")
    if is_tokenized is None and "payment_token_present" in tx_context:
        is_tokenized = tx_context.get("payment_token_present")
    if is_tokenized is None:
        is_tokenized = "unknown"

    is_known_merchant = transaction.get("is_known_merchant")
    if is_known_merchant is None and "is_known_merchant" in tx_context:
        is_known_merchant = tx_context.get("is_known_merchant")
    if is_known_merchant is None:
        is_known_merchant = "unknown"

    observations = _observation_lines(context)

    return {
        "transaction_id": transaction.get("transaction_id", "unknown"),
        "card_id": transaction.get("card_id", "unknown"),
        "card_last4": transaction.get("card_last4") or transaction.get("card_last_four") or "****",
        "amount": transaction.get("amount", 0),
        "currency": transaction.get("currency", "USD"),
        "timestamp": transaction.get("timestamp")
        or transaction.get("transaction_timestamp")
        or "unknown",
        "merchant_category": transaction.get("merchant_category", "unknown"),
        "merchant_id": transaction.get("merchant_id", "unknown"),
        "decision": transaction.get("decision") or transaction.get("status") or "unknown",
        "three_ds_authenticated": three_ds_authenticated,
        "device_trusted": device_trusted,
        "avs_match": avs_match,
        "cvv_match": cvv_match,
        "is_tokenized": is_tokenized,
        "is_known_merchant": is_known_merchant,
        "device_fingerprint": transaction.get("device_fingerprint", "unknown"),
        "card_age_days": transaction.get("card_age_days", "unknown"),
        "transaction_count_90d": velocity.get("transaction_count_90d", "unknown"),
        "approval_rate_90d": velocity.get("approval_rate_90d", 0.0),
        "velocity_24h": velocity.get("velocity_24h", "unknown"),
        "similarity_score": similarity_summary.get("overall_score", 0.0),
        "pattern_analysis": "\n".join(pattern_lines) or "  - No patterns detected",
        "similarity_analysis": "\n".join(sim_lines),
        "counter_evidence": counter_evidence_text,
        "conflict_matrix": json.dumps(conflict_matrix) if conflict_matrix else "Not computed",
        "insight_summary": context.get("insight_summary", ""),
        "observations": observations,
    }


def parse_llm_response(raw_response: str) -> dict[str, Any]:
    """Parse LLM response with multiple extraction strategies.

    Handles common LLM output formats:
    - Pure JSON
    - JSON inside ```json ... ``` or ``` ... ``` code blocks
    - JSON embedded in surrounding prose text
    - JSON with trailing commentary after closing braces

    Args:
        raw_response: Raw string response from LLM

    Returns:
        Parsed dict or error fallback dict
    """
    import re

    cleaned = raw_response.strip()

    # Strategy 1: Try direct JSON parse
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Strategy 2: Extract from ``` code blocks (with or without language tag)
    code_block_match = re.search(r"```(?:json)?\s*\n(.*?)\n```", cleaned, re.DOTALL)
    if code_block_match:
        try:
            return json.loads(code_block_match.group(1).strip())
        except json.JSONDecodeError:
            pass

    # Strategy 3: Find first { ... } JSON object in response
    brace_start = cleaned.find("{")
    if brace_start >= 0:
        depth = 0
        for i in range(brace_start, len(cleaned)):
            if cleaned[i] == "{":
                depth += 1
            elif cleaned[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(cleaned[brace_start : i + 1])
                    except json.JSONDecodeError:
                        break

    return {
        "narrative": "Unable to parse LLM response",
        "risk_assessment": "MEDIUM",
        "key_findings": ["Parse error - using default assessment"],
        "confidence": 0.0,
        "parse_error": True,
    }


def merge_reasoning_with_evidence(
    reasoning: dict[str, Any],
    deterministic: dict[str, Any],
) -> dict[str, Any]:
    """Merge LLM narrative with deterministic evidence.

    Args:
        reasoning: LLM reasoning result
        deterministic: Deterministic analysis data

    Returns:
        Merged dict with both reasoning and deterministic data
    """
    merged = {
        "narrative": reasoning.get("narrative", ""),
        "risk_assessment": reasoning.get("risk_assessment", "MEDIUM"),
        "key_findings": reasoning.get("key_findings", []),
        "confidence": reasoning.get("confidence", 0.5),
        "model_mode": "hybrid",
        "deterministic_severity": deterministic.get("severity", "UNKNOWN"),
        "pattern_scores": deterministic.get("pattern_scores", []),
        "similarity_score": deterministic.get("similarity_score", 0),
        "insight_summary": deterministic.get("insight_summary", ""),
    }

    if reasoning.get("parse_error"):
        merged["model_mode"] = "deterministic"

    return merged
