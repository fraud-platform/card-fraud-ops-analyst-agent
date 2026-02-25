"""Reasoning engine core - PURE functions for LLM reasoning preparation.

This module contains ZERO database access. Pure functions operating on in-memory data.
"""

import dataclasses
import json
import re
from typing import Any, cast

from app.tools._core.pattern_utils import to_pattern_dicts

PROMPT_INJECTION_PATTERNS = [
    re.compile(
        r"ignore\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)", re.IGNORECASE
    ),
    re.compile(
        r"disregard\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)", re.IGNORECASE
    ),
    re.compile(
        r"forget\s+(all\s+)?(previous|above|prior)\s+(instructions?|prompts?)", re.IGNORECASE
    ),
    re.compile(r"you\s+are\s+now\s+", re.IGNORECASE),
    re.compile(r"system\s*:\s*", re.IGNORECASE),
    re.compile(r"<\|.*?\|>", re.IGNORECASE),
    re.compile(r"\[system\]", re.IGNORECASE),
    re.compile(r"```system", re.IGNORECASE),
    re.compile(r"jailbreak", re.IGNORECASE),
    re.compile(r"override\s+(all\s+)?safety", re.IGNORECASE),
    re.compile(r"pretend\s+(to\s+be|you\s+are)", re.IGNORECASE),
    re.compile(r"act\s+as\s+(if|though)\s+you\s+are", re.IGNORECASE),
]

MAX_PROMPT_STRING_LENGTH = 50000
MAX_JSON_DEPTH = 10


def _normalize_to_dict(value: Any) -> dict[str, Any]:
    """Normalize a value to a dict, handling dataclasses and None."""
    if value is None:
        return {}
    if isinstance(value, dict):
        return cast(dict[str, Any], value)
    if dataclasses.is_dataclass(value) and not isinstance(value, type):
        return dataclasses.asdict(value)
    return {}


def scan_for_injection(text: str) -> list[str]:
    """Scan text for prompt injection patterns.

    Args:
        text: Text to scan for injection patterns

    Returns:
        List of detected pattern descriptions (empty if clean)
    """
    if not text or not isinstance(text, str):
        return []

    detected: list[str] = []
    for pattern in PROMPT_INJECTION_PATTERNS:
        if pattern.search(text):
            detected.append(f"matched pattern: {pattern.pattern[:50]}")
    return detected


def validate_prompt_payload(payload: dict[str, Any], max_depth: int = 0) -> list[str]:
    """Validate prompt payload for injection attempts and size limits.

    Args:
        payload: The prompt payload dictionary to validate
        max_depth: Current recursion depth (internal use)

    Returns:
        List of validation errors (empty if valid)
    """
    errors: list[str] = []

    if max_depth > MAX_JSON_DEPTH:
        errors.append(f"JSON depth exceeds maximum ({MAX_JSON_DEPTH})")
        return errors

    for key, value in payload.items():
        if isinstance(value, str):
            if len(value) > MAX_PROMPT_STRING_LENGTH:
                errors.append(
                    f"Field '{key}' exceeds max length ({len(value)} > {MAX_PROMPT_STRING_LENGTH})"
                )

            injection_detected = scan_for_injection(value)
            if injection_detected:
                errors.append(
                    f"Field '{key}' contains potential injection: {injection_detected[0]}"
                )

        elif isinstance(value, dict):
            nested_errors = validate_prompt_payload(value, max_depth + 1)
            errors.extend(nested_errors)

        elif isinstance(value, list):
            for i, item in enumerate(value):
                if isinstance(item, dict):
                    nested_errors = validate_prompt_payload(item, max_depth + 1)
                    errors.extend(nested_errors)
                elif isinstance(item, str):
                    if len(item) > MAX_PROMPT_STRING_LENGTH:
                        errors.append(f"Field '{key}[{i}]' exceeds max length")
                    injection_detected = scan_for_injection(item)
                    if injection_detected:
                        errors.append(f"Field '{key}[{i}]' contains potential injection")

    return errors


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except TypeError, ValueError:
        return default


def _normalize_similarity_match(match: Any) -> dict[str, Any] | None:
    if isinstance(match, dict):
        transaction_id = (
            match.get("transaction_id") or match.get("match_id") or match.get("id") or ""
        )
        score = _to_float(match.get("score", match.get("similarity_score", 0.0)))
        return {
            "transaction_id": transaction_id,
            "match_type": match.get("match_type", "unknown"),
            "score": score,
            "details": match.get("details", {}) or {},
            "counter_evidence": match.get("counter_evidence"),
        }

    if not any(
        hasattr(match, attr) for attr in ("transaction_id", "match_id", "score", "similarity_score")
    ):
        return None

    transaction_id = getattr(match, "transaction_id", None) or getattr(match, "match_id", "") or ""
    score = _to_float(getattr(match, "score", getattr(match, "similarity_score", 0.0)))
    return {
        "transaction_id": transaction_id,
        "match_type": getattr(match, "match_type", "unknown"),
        "score": score,
        "details": getattr(match, "details", {}) or {},
        "counter_evidence": getattr(match, "counter_evidence", None),
    }


def _normalize_similarity_matches(raw_matches: Any) -> list[dict[str, Any]]:
    if not isinstance(raw_matches, list):
        return []
    normalized: list[dict[str, Any]] = []
    for match in raw_matches:
        item = _normalize_similarity_match(match)
        if item:
            normalized.append(item)
    return normalized


def _similarity_dict(similarity_analysis: dict[str, Any]) -> dict[str, Any]:
    sim_result = similarity_analysis.get("similarity_result")
    if sim_result is not None:
        sim_result_dict = _normalize_to_dict(sim_result)
        matches = _normalize_similarity_matches(sim_result_dict.get("matches"))
        if not matches:
            matches = _normalize_similarity_matches(getattr(sim_result, "matches", []))
        if not matches:
            matches = _normalize_similarity_matches(similarity_analysis.get("matches"))
        if not matches:
            matches = _normalize_similarity_matches(similarity_analysis.get("similar_transactions"))

        raw_score = sim_result_dict.get("overall_score", getattr(sim_result, "overall_score", None))
        if raw_score is None:
            raw_score = similarity_analysis.get("overall_score", 0.0)
        return {
            "overall_score": _to_float(raw_score, 0.0),
            "matches": matches,
            "counter_evidence": sim_result_dict.get(
                "counter_evidence",
                getattr(
                    sim_result, "counter_evidence", similarity_analysis.get("counter_evidence")
                ),
            ),
        }

    matches = _normalize_similarity_matches(similarity_analysis.get("matches"))
    if not matches:
        matches = _normalize_similarity_matches(similarity_analysis.get("similar_transactions"))

    raw_overall_score = similarity_analysis.get("overall_score")
    if raw_overall_score is None and matches:
        raw_overall_score = max((m.get("score", 0.0) for m in matches), default=0.0)

    return {
        "overall_score": _to_float(raw_overall_score, 0.0),
        "matches": matches,
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


def _resolve_field(
    transaction: dict[str, Any],
    tx_context: dict[str, Any],
    txn_keys: list[str],
    ctx_keys: list[str],
    default: Any = "unknown",
) -> Any:
    """Look up a field by trying transaction keys first, then tx_context keys, with a default."""
    for key in txn_keys:
        value = transaction.get(key)
        if value is not None:
            return value
    for key in ctx_keys:
        if key in tx_context:
            return tx_context.get(key)
    return default


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
    transaction = _normalize_to_dict(context.get("transaction"))

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

    velocity = _normalize_to_dict(context.get("velocity_snapshot"))

    tx_context = _normalize_to_dict(context.get("transaction_context"))

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

    three_ds_authenticated = _resolve_field(
        transaction,
        tx_context,
        ["three_ds_authenticated", "3ds_verified"],
        ["3ds_verified"],
    )
    device_trusted = _resolve_field(transaction, tx_context, ["device_trusted"], ["device_trusted"])
    avs_match = _resolve_field(
        transaction,
        tx_context,
        ["avs_match", "avs_response"],
        ["avs_match", "avs_response"],
    )
    cvv_match = _resolve_field(
        transaction,
        tx_context,
        ["cvv_match", "cvv_response"],
        ["cvv_match", "cvv_response"],
    )
    is_tokenized = _resolve_field(
        transaction,
        tx_context,
        ["is_tokenized", "payment_token_present"],
        ["is_tokenized", "payment_token_present"],
    )
    is_known_merchant = _resolve_field(
        transaction, tx_context, ["is_known_merchant"], ["is_known_merchant"]
    )

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


VALID_RISK_LEVELS = frozenset({"CRITICAL", "HIGH", "MEDIUM", "LOW", "UNKNOWN"})
MAX_NARRATIVE_LENGTH = 2000
MAX_FINDINGS_COUNT = 20
MAX_HYPOTHESES_COUNT = 10


def validate_llm_output(parsed: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Validate and sanitize LLM output for safety and consistency.

    Args:
        parsed: The parsed LLM response dictionary

    Returns:
        Tuple of (sanitized_output, warnings_list)
    """
    warnings: list[str] = []
    sanitized = dict(parsed)

    narrative = parsed.get("narrative", "")
    if isinstance(narrative, str):
        if len(narrative) > MAX_NARRATIVE_LENGTH:
            sanitized["narrative"] = narrative[:MAX_NARRATIVE_LENGTH] + "...[truncated]"
            warnings.append(
                f"narrative truncated from {len(narrative)} to {MAX_NARRATIVE_LENGTH} chars"
            )

        injection_detected = scan_for_injection(narrative)
        if injection_detected:
            sanitized["narrative"] = "[content sanitized due to detected pattern]"
            warnings.append("narrative contained potential injection pattern")

    risk_level = parsed.get("risk_level", "MEDIUM")
    if isinstance(risk_level, str):
        risk_upper = risk_level.upper().strip()
        if risk_upper not in VALID_RISK_LEVELS:
            sanitized["risk_level"] = "MEDIUM"
            warnings.append(f"risk_level '{risk_level}' normalized to MEDIUM")
        else:
            sanitized["risk_level"] = risk_upper
    else:
        sanitized["risk_level"] = "MEDIUM"
        warnings.append("risk_level missing or invalid, defaulted to MEDIUM")

    confidence = parsed.get("confidence")
    if confidence is not None:
        try:
            conf_float = float(confidence)
            if not 0.0 <= conf_float <= 1.0:
                sanitized["confidence"] = max(0.0, min(1.0, conf_float))
                warnings.append(f"confidence {conf_float} clamped to {sanitized['confidence']}")
            else:
                sanitized["confidence"] = conf_float
        except TypeError, ValueError:
            sanitized["confidence"] = 0.5
            warnings.append("confidence invalid, defaulted to 0.5")
    else:
        sanitized["confidence"] = 0.5

    key_findings = parsed.get("key_findings", [])
    if isinstance(key_findings, list):
        sanitized_findings = []
        for i, finding in enumerate(key_findings[:MAX_FINDINGS_COUNT]):
            if isinstance(finding, str):
                clean_finding = finding[:500]
                if scan_for_injection(clean_finding):
                    clean_finding = "[finding sanitized]"
                    warnings.append(f"key_findings[{i}] contained potential injection")
                sanitized_findings.append(clean_finding)
        if len(key_findings) > MAX_FINDINGS_COUNT:
            warnings.append(
                f"key_findings truncated from {len(key_findings)} to {MAX_FINDINGS_COUNT}"
            )
        sanitized["key_findings"] = sanitized_findings
    else:
        sanitized["key_findings"] = []
        warnings.append("key_findings invalid, defaulted to empty list")

    hypotheses = parsed.get("hypotheses", [])
    if isinstance(hypotheses, list):
        sanitized_hypotheses = []
        for i, hyp in enumerate(hypotheses[:MAX_HYPOTHESES_COUNT]):
            if isinstance(hyp, str):
                clean_hyp = hyp[:300]
                if scan_for_injection(clean_hyp):
                    clean_hyp = "[hypothesis sanitized]"
                    warnings.append(f"hypotheses[{i}] contained potential injection")
                sanitized_hypotheses.append(clean_hyp)
        if len(hypotheses) > MAX_HYPOTHESES_COUNT:
            warnings.append(
                f"hypotheses truncated from {len(hypotheses)} to {MAX_HYPOTHESES_COUNT}"
            )
        sanitized["hypotheses"] = sanitized_hypotheses
    else:
        sanitized["hypotheses"] = []

    for sensitive_key in ("system", "instruction", "override", "password", "secret", "token"):
        if sensitive_key in sanitized:
            del sanitized[sensitive_key]
            warnings.append(f"removed sensitive key: {sensitive_key}")

    if warnings:
        sanitized["_validation_warnings"] = warnings

    return sanitized, warnings


def _strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```(?:json)?\s*", "", stripped, flags=re.IGNORECASE)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def _extract_balanced_json(text: str) -> str | None:
    start = text.find("{")
    if start < 0:
        return None

    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escape:
                escape = False
            elif ch == "\\":
                escape = True
            elif ch == '"':
                in_string = False
            continue

        if ch == '"':
            in_string = True
            continue
        if ch == "{":
            depth += 1
            continue
        if ch == "}":
            depth -= 1
            if depth == 0:
                return text[start : i + 1]
    return None


def _extract_string_field(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"((?:\\.|[^"\\])*)"', text, flags=re.DOTALL)
    if not match:
        return None
    raw = match.group(1)
    try:
        return json.loads(f'"{raw}"')
    except json.JSONDecodeError:
        return raw


def _extract_open_string_field(text: str, key: str) -> str | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*"([\s\S]+)', text, flags=re.DOTALL)
    if not match:
        return None
    tail = match.group(1)
    stop_markers = (
        '",\n  "risk_level"',
        '",\n "risk_level"',
        '", "risk_level"',
        '","risk_level"',
        '"\n}',
        '"}',
    )
    end = len(tail)
    for marker in stop_markers:
        idx = tail.find(marker)
        if idx >= 0:
            end = min(end, idx)
    candidate = tail[:end].strip().strip(",")
    if not candidate:
        return None
    return candidate[:600]


def _extract_float_field(text: str, key: str) -> float | None:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(-?\d+(?:\.\d+)?)', text)
    if not match:
        return None
    try:
        return float(match.group(1))
    except TypeError, ValueError:
        return None


def _extract_string_array_field(text: str, key: str) -> list[str]:
    match = re.search(rf'"{re.escape(key)}"\s*:\s*(\[[\s\S]*?\])', text, flags=re.DOTALL)
    if not match:
        return []
    try:
        parsed = json.loads(match.group(1))
    except json.JSONDecodeError:
        return []
    if not isinstance(parsed, list):
        return []
    return [item for item in parsed if isinstance(item, str)]


def _partial_parse_llm_response(text: str) -> dict[str, Any] | None:
    narrative = _extract_string_field(text, "narrative")
    if not narrative:
        narrative = _extract_open_string_field(text, "narrative")

    risk_level = _extract_string_field(text, "risk_level")
    if not risk_level:
        fallback_risk = re.search(
            r'"?risk_level"?\s*:\s*"?(CRITICAL|HIGH|MEDIUM|LOW|UNKNOWN)"?',
            text,
            flags=re.IGNORECASE,
        )
        if fallback_risk:
            risk_level = fallback_risk.group(1)
    confidence = _extract_float_field(text, "confidence")
    findings = _extract_string_array_field(text, "key_findings")
    hypotheses = _extract_string_array_field(text, "hypotheses")

    if isinstance(risk_level, str):
        risk_level = risk_level.upper().strip()
        if risk_level not in VALID_RISK_LEVELS:
            risk_level = None

    if not (narrative or risk_level or confidence is not None):
        return None

    payload: dict[str, Any] = {
        "narrative": narrative or "Model returned partial JSON response",
        "risk_level": risk_level or "MEDIUM",
        "key_findings": findings,
        "hypotheses": hypotheses,
        "confidence": confidence if confidence is not None else 0.5,
        "_partial_parse": True,
    }
    if narrative:
        payload["summary"] = narrative
    return validate_llm_output(payload)[0]


def parse_llm_response(raw_response: str) -> dict[str, Any]:
    """Parse and validate LLM response with strict-then-fallback strategies."""
    cleaned = raw_response.strip()
    stripped_fences = _strip_markdown_fences(cleaned)

    candidates: list[str] = []
    seen: set[str] = set()

    def add_candidate(candidate: str | None) -> None:
        if not isinstance(candidate, str):
            return
        value = candidate.strip()
        if not value or value in seen:
            return
        seen.add(value)
        candidates.append(value)

    add_candidate(cleaned)
    add_candidate(stripped_fences)

    for match in re.finditer(r"```(?:json)?\s*([\s\S]*?)```", cleaned, flags=re.IGNORECASE):
        add_candidate(match.group(1))

    add_candidate(_extract_balanced_json(cleaned))
    add_candidate(_extract_balanced_json(stripped_fences))

    for candidate in candidates:
        try:
            parsed = json.loads(candidate)
            return validate_llm_output(parsed)[0]
        except json.JSONDecodeError:
            continue

    partial = _partial_parse_llm_response(cleaned) or _partial_parse_llm_response(stripped_fences)
    if partial is not None:
        return partial

    raise ValueError("Unable to parse LLM response into expected JSON schema")
