"""Similarity engine core - PURE functions for threshold evaluation and freshness weighting.

This module contains ZERO database access. Pure functions operating on in-memory data structures.
"""

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any


@dataclass(frozen=True)
class SimilarityMatch:
    """Immutable similarity match result."""

    match_id: str
    match_type: str
    similarity_score: float
    details: dict[str, Any]
    counter_evidence: list[dict[str, Any]] | None = None


@dataclass(frozen=True)
class SimilarityResult:
    """Immutable similarity analysis result."""

    matches: list[SimilarityMatch]
    overall_score: float
    counter_evidence: list[dict[str, Any]] | None = None


def freshness_weight(transaction_timestamp: datetime | None) -> float:
    """Compute freshness weight based on transaction timestamp."""
    if transaction_timestamp is None:
        return 0.5

    now = datetime.now(UTC)
    age = now - transaction_timestamp

    if age < timedelta(hours=1):
        return 1.0
    elif age < timedelta(hours=6):
        return 0.9
    elif age < timedelta(hours=24):
        return 0.7
    elif age < timedelta(days=7):
        return 0.5
    else:
        return 0.3


def evaluate_similarity(
    transaction: Any,
    similar_transactions: list[dict[str, Any]],
) -> SimilarityResult:
    """Evaluate similarity to other transactions."""
    matches = []

    if not similar_transactions:
        return SimilarityResult(matches=[], overall_score=0.0)

    if hasattr(transaction, "transaction_timestamp"):
        tx_timestamp = transaction.transaction_timestamp
    else:
        tx_timestamp = (
            transaction.get("transaction_timestamp") if isinstance(transaction, dict) else None
        )

    freshness = freshness_weight(tx_timestamp)

    if hasattr(transaction, "amount"):
        amount = _to_float(transaction.amount)
        merchant_id = transaction.merchant_id
        card_id = transaction.card_id
    else:
        amount = _to_float(transaction.get("amount", 0)) if isinstance(transaction, dict) else 0.0
        merchant_id = transaction.get("merchant_id") if isinstance(transaction, dict) else None
        card_id = transaction.get("card_id") if isinstance(transaction, dict) else None

    all_counter_evidence: list[dict[str, Any]] = []
    for sim_tx in similar_transactions:
        counter_evidence_payload = _extract_counter_evidence(sim_tx)
        if counter_evidence_payload:
            all_counter_evidence.append(counter_evidence_payload)

        base_score = sim_tx.get("similarity_score")
        match_type = sim_tx.get("match_type")
        details = sim_tx.get("details")

        if base_score is None:
            score = 0.0
            computed_details: dict[str, Any] = {}

            sim_amount = _to_float(sim_tx.get("amount", 0))
            if amount > 0 and sim_amount > 0:
                amount_ratio = min(amount, sim_amount) / max(amount, sim_amount)
                if amount_ratio > 0.8:
                    score += 0.4 * amount_ratio
                    computed_details["amount_ratio"] = amount_ratio

            if merchant_id and sim_tx.get("merchant_id") == merchant_id:
                score += 0.3
                computed_details["same_merchant"] = True

            if card_id and sim_tx.get("card_id") == card_id:
                score += 0.3
                computed_details["same_card"] = True

            base_score = score
            match_type = match_type or "transaction_pattern"
            details = details or computed_details
        else:
            match_type = match_type or "precomputed"
            details = details or {}

        if base_score and base_score > 0:
            risk_multiplier = _risk_multiplier(sim_tx, counter_evidence_payload)
            weighted_score = float(base_score) * freshness * risk_multiplier
            normalized_details = dict(details)
            normalized_details["risk_multiplier"] = round(risk_multiplier, 6)
            matches.append(
                SimilarityMatch(
                    match_id=sim_tx.get("transaction_id", ""),
                    match_type=str(match_type),
                    similarity_score=weighted_score,
                    details=normalized_details,
                    counter_evidence=(
                        counter_evidence_payload.get("counter_evidence")
                        if counter_evidence_payload
                        else None
                    ),
                )
            )

    matches.sort(key=lambda m: m.similarity_score, reverse=True)
    top_matches = matches[:5]

    overall = (
        sum(m.similarity_score for m in top_matches) / len(top_matches) if top_matches else 0.0
    )

    return SimilarityResult(
        matches=top_matches,
        overall_score=overall,
        counter_evidence=all_counter_evidence if all_counter_evidence else None,
    )


def _to_float(value: Any) -> float:
    if isinstance(value, float):
        return value
    if isinstance(value, int):
        return float(value)
    if isinstance(value, Decimal):
        return float(value)
    try:
        return float(value)
    except TypeError, ValueError:
        return 0.0


def _risk_multiplier(
    sim_tx: dict[str, Any],
    counter_evidence_payload: dict[str, Any] | None,
) -> float:
    """Compute risk multiplier for a match.

    Similarity to approved transactions with strong counter-evidence should
    contribute less to fraud risk than similarity to declined/flagged flows.
    """
    decision = str(sim_tx.get("decision", "")).strip().upper()
    if decision in {"APPROVE", "APPROVED"}:
        decision_multiplier = 0.65
    elif decision in {"DECLINE", "DECLINED"}:
        decision_multiplier = 1.0
    elif decision:
        decision_multiplier = 0.85
    else:
        decision_multiplier = 1.0

    if not counter_evidence_payload:
        return decision_multiplier

    evidence_items = counter_evidence_payload.get("counter_evidence", [])
    if not evidence_items:
        return decision_multiplier

    avg_strength = sum(float(item.get("strength", 0.0)) for item in evidence_items) / len(
        evidence_items
    )
    counter_multiplier = max(0.25, 1.0 - (avg_strength * 0.8))
    return decision_multiplier * counter_multiplier


def _extract_counter_evidence(sim_tx: dict[str, Any]) -> dict[str, Any] | None:
    evidence_list = []

    if sim_tx.get("three_ds_authenticated") is True:
        evidence_list.append(
            {
                "type": "3ds_success",
                "strength": 0.8,
                "description": "Similar transaction had successful 3DS authentication",
            }
        )

    if sim_tx.get("is_trusted_device") is True:
        evidence_list.append(
            {
                "type": "trusted_device",
                "strength": 0.7,
                "description": "Transaction from trusted device with good history",
            }
        )

    if sim_tx.get("avs_match") is True or sim_tx.get("avs_response") == "Y":
        evidence_list.append(
            {
                "type": "avs_match",
                "strength": 0.6,
                "description": "Address Verification Service (AVS) matched - billing address verified",
            }
        )

    if sim_tx.get("cvv_match") is True or sim_tx.get("cvv_response") == "Y":
        evidence_list.append(
            {
                "type": "cvv_match",
                "strength": 0.6,
                "description": "CVV/CVC verification passed - card security code validated",
            }
        )

    if sim_tx.get("is_tokenized") is True or sim_tx.get("payment_token_present") is True:
        evidence_list.append(
            {
                "type": "tokenized_payment",
                "strength": 0.5,
                "description": "Tokenized payment method - reduced fraud risk",
            }
        )

    if sim_tx.get("is_recurring_customer") is True or sim_tx.get("recurring_payment") is True:
        evidence_list.append(
            {
                "type": "recurring_customer",
                "strength": 0.4,
                "description": "Known recurring customer with established payment history",
            }
        )

    if sim_tx.get("cardholder_present") is True:
        evidence_list.append(
            {
                "type": "cardholder_present",
                "strength": 0.5,
                "description": "Cardholder present at time of transaction",
            }
        )

    if sim_tx.get("is_known_merchant") is True:
        evidence_list.append(
            {
                "type": "known_merchant",
                "strength": 0.4,
                "description": "Transaction at known/trusted merchant",
            }
        )

    if evidence_list:
        return {"counter_evidence": evidence_list}
    return None
