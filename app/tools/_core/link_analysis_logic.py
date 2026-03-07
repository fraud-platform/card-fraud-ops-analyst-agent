"""Pure link-analysis logic based on card and merchant history.

Phase 2A intentionally uses only already-available context data:
- current transaction
- context.card_history
- context.merchant_history

No network/database calls are performed in this module.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

WINDOWS_MINUTES_CARD = {
    "5m": 5,
    "1h": 60,
    "24h": 24 * 60,
}

WINDOWS_MINUTES_MERCHANT = {
    "1h": 60,
    "24h": 24 * 60,
}


def _to_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        normalized = raw.replace("Z", "+00:00")
        try:
            dt = datetime.fromisoformat(normalized)
        except ValueError:
            return None
    else:
        return None

    if dt.tzinfo is None:
        return dt.replace(tzinfo=UTC)
    return dt


def _extract_timestamp(item: dict[str, Any]) -> datetime | None:
    for key in (
        "transaction_timestamp",
        "timestamp",
        "occurred_at",
        "created_at",
        "ingestion_timestamp",
    ):
        if key in item:
            parsed = _to_datetime(item.get(key))
            if parsed is not None:
                return parsed
    return None


def _resolve_reference_timestamp(
    transaction: dict[str, Any],
    card_history: list[dict[str, Any]],
    merchant_history: list[dict[str, Any]],
) -> datetime:
    transaction_ts = _extract_timestamp(transaction)
    if transaction_ts is not None:
        return transaction_ts

    history_timestamps: list[datetime] = []
    for entry in [*card_history, *merchant_history]:
        if not isinstance(entry, dict):
            continue
        ts = _extract_timestamp(entry)
        if ts is not None:
            history_timestamps.append(ts)

    if history_timestamps:
        return max(history_timestamps)

    return datetime(1970, 1, 1, tzinfo=UTC)


def _minutes_between(later: datetime, earlier: datetime | None) -> float | None:
    if earlier is None:
        return None
    delta = later - earlier
    return delta.total_seconds() / 60.0


def _within_window(reference_ts: datetime, event_ts: datetime | None, window_minutes: int) -> bool:
    minutes = _minutes_between(reference_ts, event_ts)
    return minutes is not None and 0.0 <= minutes <= float(window_minutes)


def _distinct_count(
    entries: list[dict[str, Any]],
    *,
    reference_ts: datetime,
    window_minutes: int,
    field_name: str,
) -> int:
    values: set[str] = set()
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        event_ts = _extract_timestamp(entry)
        if not _within_window(reference_ts, event_ts, window_minutes):
            continue
        value = entry.get(field_name)
        if isinstance(value, str) and value.strip():
            values.add(value.strip())
    return len(values)


def _bounded_ratio(numerator: float, denominator: float) -> float:
    if denominator <= 0:
        return 0.0
    return max(0.0, min(1.0, numerator / denominator))


def _round(value: float) -> float:
    return round(float(value), 4)


def run_link_analysis(
    *,
    transaction: dict[str, Any],
    card_history: list[dict[str, Any]],
    merchant_history: list[dict[str, Any]],
) -> dict[str, Any]:
    """Compute link-analysis metrics and hypotheses from existing histories.

    Returns a stable JSON-serializable payload:
    {
      "metrics": {...},
      "signals": [...],
      "hypotheses": [...],
      "summary": "...",
      "overall_score": 0.0-1.0,
    }
    """
    safe_transaction = transaction if isinstance(transaction, dict) else {}
    safe_card_history = [entry for entry in card_history if isinstance(entry, dict)]
    safe_merchant_history = [entry for entry in merchant_history if isinstance(entry, dict)]

    reference_ts = _resolve_reference_timestamp(
        safe_transaction,
        safe_card_history,
        safe_merchant_history,
    )

    card_distinct_merchants = {
        window: _distinct_count(
            safe_card_history,
            reference_ts=reference_ts,
            window_minutes=minutes,
            field_name="merchant_id",
        )
        for window, minutes in WINDOWS_MINUTES_CARD.items()
    }
    merchant_distinct_cards = {
        window: _distinct_count(
            safe_merchant_history,
            reference_ts=reference_ts,
            window_minutes=minutes,
            field_name="card_id",
        )
        for window, minutes in WINDOWS_MINUTES_MERCHANT.items()
    }

    card_burst_score = max(
        _bounded_ratio(card_distinct_merchants["5m"], 3.0),
        _bounded_ratio(card_distinct_merchants["1h"], 6.0),
        _bounded_ratio(card_distinct_merchants["24h"], 12.0),
    )
    merchant_burst_score = max(
        _bounded_ratio(merchant_distinct_cards["1h"], 8.0),
        _bounded_ratio(merchant_distinct_cards["24h"], 20.0),
    )

    signals: list[str] = []
    hypotheses: list[dict[str, Any]] = []

    if card_distinct_merchants["5m"] >= 3 or card_distinct_merchants["1h"] >= 6:
        signals.append("card_testing_signature")
        hypotheses.append(
            {
                "hypothesis": "Card testing pattern likely (rapid card fan-out to multiple merchants).",
                "confidence": _round(max(0.55, card_burst_score)),
                "supporting_evidence": [
                    f"distinct_merchants_5m={card_distinct_merchants['5m']}",
                    f"distinct_merchants_1h={card_distinct_merchants['1h']}",
                    f"card_fan_out_burst_score={_round(card_burst_score)}",
                ],
            }
        )

    if merchant_distinct_cards["1h"] >= 8:
        signals.append("mule_merchant_signature")
        hypotheses.append(
            {
                "hypothesis": "Merchant fan-in indicates potential mule merchant coordination.",
                "confidence": _round(max(0.6, merchant_burst_score)),
                "supporting_evidence": [
                    f"distinct_cards_1h={merchant_distinct_cards['1h']}",
                    f"merchant_fan_in_burst_score={_round(merchant_burst_score)}",
                ],
            }
        )

    compromised_indicator = (
        merchant_distinct_cards["24h"] >= 20 and card_distinct_merchants["1h"] >= 4
    )
    if compromised_indicator:
        signals.append("compromised_merchant_signature")
        hypotheses.append(
            {
                "hypothesis": "Cross-card concentration suggests possible compromised merchant ecosystem.",
                "confidence": _round(
                    max(0.65, (merchant_burst_score * 0.6) + (card_burst_score * 0.4))
                ),
                "supporting_evidence": [
                    f"distinct_cards_24h={merchant_distinct_cards['24h']}",
                    f"distinct_merchants_1h={card_distinct_merchants['1h']}",
                ],
            }
        )

    overall_score = _round(
        max(
            card_burst_score,
            merchant_burst_score,
            max((float(item["confidence"]) for item in hypotheses), default=0.0),
        )
    )

    if signals:
        summary = (
            "Link-analysis detected "
            + ", ".join(signals)
            + f" (overall_score={overall_score:.2f})."
        )
    else:
        summary = "Link-analysis found no strong ring signatures in card/merchant histories."

    return {
        "metrics": {
            "card_fan_out": {
                "distinct_merchants_5m": card_distinct_merchants["5m"],
                "distinct_merchants_1h": card_distinct_merchants["1h"],
                "distinct_merchants_24h": card_distinct_merchants["24h"],
                "burst_score": _round(card_burst_score),
            },
            "merchant_fan_in": {
                "distinct_cards_1h": merchant_distinct_cards["1h"],
                "distinct_cards_24h": merchant_distinct_cards["24h"],
                "burst_score": _round(merchant_burst_score),
            },
        },
        "signals": signals,
        "hypotheses": hypotheses,
        "summary": summary,
        "overall_score": overall_score,
    }


def augment_link_analysis_with_neighborhoods(
    base_result: dict[str, Any],
    *,
    current_transaction_id: str | None,
    ip_neighbors: list[dict[str, Any]],
    device_neighbors: list[dict[str, Any]],
    fingerprint_neighbors: list[dict[str, Any]],
) -> dict[str, Any]:
    """Merge TM neighborhood lookups into link-analysis metrics/signals.

    This function is pure and deterministic. It assumes neighborhood lists
    were already fetched from TM and only computes additional features.
    """

    def _filtered(items: list[dict[str, Any]]) -> list[dict[str, Any]]:
        tx_id = (current_transaction_id or "").strip()
        if not tx_id:
            return list(items)
        return [entry for entry in items if str(entry.get("transaction_id", "")).strip() != tx_id]

    def _distinct(items: list[dict[str, Any]], key: str) -> int:
        values: set[str] = set()
        for entry in items:
            value = entry.get(key)
            if isinstance(value, str) and value.strip():
                values.add(value.strip())
        return len(values)

    ip = _filtered(ip_neighbors)
    device = _filtered(device_neighbors)
    fingerprint = _filtered(fingerprint_neighbors)

    ip_distinct_cards = _distinct(ip, "card_id")
    device_distinct_cards = _distinct(device, "card_id")
    fingerprint_distinct_cards = _distinct(fingerprint, "card_id")

    ip_cluster_score = _bounded_ratio(len(ip), 8.0)
    device_cluster_score = _bounded_ratio(len(device), 8.0)
    fingerprint_cluster_score = _bounded_ratio(len(fingerprint), 8.0)

    signals = list(base_result.get("signals", []))
    hypotheses = list(base_result.get("hypotheses", []))

    if len(ip) >= 3 and ip_distinct_cards >= 3:
        signals.append("ip_cluster_signature")
        hypotheses.append(
            {
                "hypothesis": "IP neighborhood links multiple cards, suggesting coordinated activity.",
                "confidence": _round(max(0.55, ip_cluster_score)),
                "supporting_evidence": [
                    f"ip_neighbor_count={len(ip)}",
                    f"ip_distinct_cards={ip_distinct_cards}",
                ],
            }
        )

    if len(device) >= 3 and device_distinct_cards >= 3:
        signals.append("device_cluster_signature")
        hypotheses.append(
            {
                "hypothesis": "Device neighborhood spans multiple cards, indicating cross-card linkage.",
                "confidence": _round(max(0.6, device_cluster_score)),
                "supporting_evidence": [
                    f"device_neighbor_count={len(device)}",
                    f"device_distinct_cards={device_distinct_cards}",
                ],
            }
        )

    if len(fingerprint) >= 3 and fingerprint_distinct_cards >= 3:
        signals.append("fingerprint_cluster_signature")
        hypotheses.append(
            {
                "hypothesis": "Device fingerprint neighborhood links multiple cards.",
                "confidence": _round(max(0.65, fingerprint_cluster_score)),
                "supporting_evidence": [
                    f"fingerprint_neighbor_count={len(fingerprint)}",
                    f"fingerprint_distinct_cards={fingerprint_distinct_cards}",
                ],
            }
        )

    if (
        sum(int(len(group) > 0) for group in (ip, device, fingerprint)) >= 2
        and (ip_distinct_cards + device_distinct_cards + fingerprint_distinct_cards) >= 6
    ):
        signals.append("cross_card_device_ip_cluster")

    neighborhood_score = max(ip_cluster_score, device_cluster_score, fingerprint_cluster_score)
    overall_score = _round(
        max(float(base_result.get("overall_score", 0.0) or 0.0), neighborhood_score)
    )

    merged_metrics = dict(base_result.get("metrics", {}))
    merged_metrics["neighborhood_clusters"] = {
        "ip_neighbor_count": len(ip),
        "ip_distinct_cards": ip_distinct_cards,
        "ip_cluster_score": _round(ip_cluster_score),
        "device_neighbor_count": len(device),
        "device_distinct_cards": device_distinct_cards,
        "device_cluster_score": _round(device_cluster_score),
        "fingerprint_neighbor_count": len(fingerprint),
        "fingerprint_distinct_cards": fingerprint_distinct_cards,
        "fingerprint_cluster_score": _round(fingerprint_cluster_score),
    }

    unique_signals = list(dict.fromkeys(str(item) for item in signals if isinstance(item, str)))
    if unique_signals:
        summary = (
            "Link-analysis detected "
            + ", ".join(unique_signals)
            + f" (overall_score={overall_score:.2f})."
        )
    else:
        summary = "Link-analysis found no strong ring signatures in card/merchant/device/IP neighborhoods."

    return {
        **base_result,
        "metrics": merged_metrics,
        "signals": unique_signals,
        "hypotheses": hypotheses,
        "summary": summary,
        "overall_score": overall_score,
    }
