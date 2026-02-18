"""Seed test transactions for scenario-based E2E testing.

This script creates deterministic test transactions for each fraud scenario:
1. clear_fraud_001 — Card testing pattern (multiple declines, different merchants)
2. clear_fraud_002 — Velocity abuse (5 transactions in 5 minutes, high amount)
3. clear_fraud_003 — Geographic anomaly (unlikely location for cardholder)
4. likely_fraud_001 — New merchant, slightly elevated amount
5. legitimate_001 — Normal pattern, trusted merchant, 3DS success
6. approved_likely_fraud_001 — Approved but suspicious (high amount, no 3DS, new merchant)
7. edge_first_txn_001 — First transaction on new card
8. edge_missing_data_001 — Transaction with missing optional fields

Usage:
    doppler run --config local -- python scripts/seed_test_scenarios.py

The script is idempotent — running it multiple times is safe.
"""

from __future__ import annotations

import json
import os
import uuid
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import psycopg

from app.core.config import to_libpq_url

# Use admin URL for DML. No hardcoded fallback credentials.
_DATABASE_URL = os.getenv("DATABASE_URL_ADMIN") or os.getenv("DATABASE_URL")
if not _DATABASE_URL:
    raise SystemExit(
        "DATABASE_URL_ADMIN or DATABASE_URL must be set. Run via Doppler (no local DSN fallback)."
    )

# psycopg needs libpq-style URLs and must not receive SQLAlchemy engine kwargs in the query string.
DATABASE_URL = to_libpq_url(_DATABASE_URL)
SEED_CONTEXT_MARKER = "ops-agent-e2e"
SEED_CONTEXT_VERSION = "2026-02-17"
SEED_MANIFEST_PATH = Path(os.getenv("E2E_SEED_MANIFEST", "htmlcov/e2e-seed-manifest.json"))


def generate_uuid7() -> str:
    """Generate a UUID7 (time-ordered) for consistent test data."""
    if hasattr(uuid, "uuid7"):
        return str(uuid.uuid7())
    return str(uuid.uuid4())


def clear_test_data(conn: psycopg.Connection) -> None:
    """Clear existing test scenario data."""
    print("[CLEAN] Clearing existing test scenario data...")
    with conn.cursor() as cur:
        cur.execute(
            """
            SELECT id, transaction_id::text
            FROM fraud_gov.transactions
            WHERE
                merchant_id LIKE 'test-merchant-%'
                OR merchant_id LIKE 'merchant_velocity_%'
                OR merchant_id LIKE 'merchant_retail_%'
                OR merchant_id LIKE 'merchant_unknown_%'
                OR card_id LIKE 'tok_cardtest_%'
                OR card_id LIKE 'tok_velocity_%'
                OR card_id LIKE 'tok_burst_%'
                OR card_id LIKE 'tok_cross_%'
                OR card_id LIKE 'tok_decline_%'
                OR card_id LIKE 'tok_counter_%'
                OR card_id LIKE 'tok_likely_%'
                OR card_id LIKE 'tok_legit_%'
                OR card_id LIKE 'tok_approved_fraud_%'
                OR card_id LIKE 'tok_first_%'
                OR card_id LIKE 'tok_missing_%'
                OR card_id LIKE 'tok_round_%'
                OR card_id LIKE 'tok_highamt_%'
                OR card_id LIKE 'tok_latenight_%'
                OR card_id LIKE 'tok_tz_%'
                OR card_id LIKE 'tok_extcounter_%'
                OR card_id LIKE 'tok_cardtestseq_%'
        """
        )
        txn_rows = cur.fetchall()
        txn_pk_ids = [row[0] for row in txn_rows]
        txn_ids = [row[1] for row in txn_rows]

        if txn_pk_ids:
            # Resolve dependent insight/recommendation IDs first.
            cur.execute(
                """
                SELECT insight_id
                FROM fraud_gov.ops_agent_insights
                WHERE transaction_pk_id = ANY(%s) OR transaction_id::text = ANY(%s)
            """,
                [txn_pk_ids, txn_ids],
            )
            insight_ids = [row[0] for row in cur.fetchall()]

            rec_ids: list[str] = []
            if insight_ids:
                cur.execute(
                    """
                    SELECT recommendation_id
                    FROM fraud_gov.ops_agent_recommendations
                    WHERE insight_id = ANY(%s)
                """,
                    [insight_ids],
                )
                rec_ids = [row[0] for row in cur.fetchall()]

            if rec_ids:
                cur.execute(
                    """
                    DELETE FROM fraud_gov.ops_agent_rule_drafts
                    WHERE recommendation_id = ANY(%s)
                """,
                    [rec_ids],
                )
                cur.execute(
                    """
                    DELETE FROM fraud_gov.ops_agent_recommendations
                    WHERE recommendation_id = ANY(%s)
                """,
                    [rec_ids],
                )

            if insight_ids:
                cur.execute(
                    """
                    DELETE FROM fraud_gov.ops_agent_evidence
                    WHERE insight_id = ANY(%s)
                """,
                    [insight_ids],
                )
                cur.execute(
                    """
                    DELETE FROM fraud_gov.ops_agent_insights
                    WHERE insight_id = ANY(%s)
                """,
                    [insight_ids],
                )

            cur.execute(
                """
                DELETE FROM fraud_gov.ops_agent_runs
                WHERE split_part(trigger_ref, ' ', 1) = ANY(%s)
            """,
                [[f"transaction:{txn_id}" for txn_id in txn_ids]],
            )

            # Delete seeded TM rows last.
            cur.execute(
                """
                DELETE FROM fraud_gov.transaction_rule_matches
                WHERE transaction_id = ANY(%s)
            """,
                [txn_pk_ids],
            )

            cur.execute(
                """
                DELETE FROM fraud_gov.transactions
                WHERE id = ANY(%s)
            """,
                [txn_pk_ids],
            )
            print(f"[CLEAN] Removed {len(txn_pk_ids)} seeded transactions and dependent rows")
        else:
            print("[CLEAN] No previously seeded scenario transactions found")

    conn.commit()
    print("[CLEAN] Done")


def build_velocity_snapshot(
    transaction_count_90d: int,
    approved_count_90d: int,
    *,
    velocity_24h: int | None = None,
) -> dict[str, float | int]:
    """Build a normalized velocity snapshot payload for seeded transactions."""
    count = max(int(transaction_count_90d), 1)
    approved = max(0, min(int(approved_count_90d), count))
    return {
        "velocity_24h": int(velocity_24h if velocity_24h is not None else count),
        "transaction_count_90d": count,
        "approval_rate_90d": round(approved / count, 2),
    }


def apply_velocity_snapshots(transactions: list[dict]) -> None:
    """Populate velocity snapshots for scenario timelines when absent.

    The list order represents chronological progression in all seed builders.
    """
    approved_count = 0
    for idx, txn in enumerate(transactions, start=1):
        if str(txn.get("decision", "")).upper() == "APPROVE":
            approved_count += 1
        if txn.get("velocity_snapshot") is None:
            txn["velocity_snapshot"] = build_velocity_snapshot(
                transaction_count_90d=idx,
                approved_count_90d=approved_count,
                velocity_24h=idx,
            )


def with_seed_context(
    txn: dict[str, Any],
    *,
    scenario: str,
    sequence: int,
    is_target: bool,
) -> dict[str, Any]:
    """Attach deterministic seed markers used by E2E scenario selection."""
    context = dict(txn.get("transaction_context") or {})
    context.update(
        {
            "seed_marker": SEED_CONTEXT_MARKER,
            "seed_version": SEED_CONTEXT_VERSION,
            "seed_scenario": scenario,
            "seed_sequence": sequence,
            "seed_is_target": is_target,
        }
    )
    txn["transaction_context"] = context
    return txn


def annotate_scenario_transactions(
    scenario: str,
    transactions: list[dict[str, Any]],
    *,
    target_index: int = -1,
) -> None:
    """Annotate a scenario timeline so E2E tests can select the exact target row."""
    if not transactions:
        return
    normalized_target = target_index if target_index >= 0 else len(transactions) + target_index
    for idx, txn in enumerate(transactions):
        with_seed_context(
            txn,
            scenario=scenario,
            sequence=idx + 1,
            is_target=idx == normalized_target,
        )


def write_seed_manifest(scenarios: dict[str, str]) -> None:
    """Persist seeded target transaction IDs for deterministic E2E lookup."""
    payload = {
        "seed_marker": SEED_CONTEXT_MARKER,
        "seed_version": SEED_CONTEXT_VERSION,
        "generated_at": datetime.now(UTC).isoformat(),
        "scenarios": scenarios,
    }
    SEED_MANIFEST_PATH.parent.mkdir(parents=True, exist_ok=True)
    SEED_MANIFEST_PATH.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(f"[SEED] Wrote manifest: {SEED_MANIFEST_PATH}")


def validate_seed_quality(conn: psycopg.Connection, scenarios: dict[str, str]) -> None:
    """Validate seeded targets exist, are recent, and carry deterministic seed markers."""
    stale_cutoff = datetime.now(UTC) - timedelta(hours=72)
    exempt_velocity = {"edge_missing_data"}
    missing_transactions: list[str] = []
    stale_transactions: list[str] = []
    missing_context_markers: list[str] = []
    missing_velocity_snapshots: list[str] = []

    with conn.cursor() as cur:
        for scenario, transaction_id in scenarios.items():
            cur.execute(
                """
                SELECT transaction_timestamp, transaction_context, velocity_snapshot
                FROM fraud_gov.transactions
                WHERE transaction_id::text = %s
                ORDER BY transaction_timestamp DESC
                LIMIT 1
            """,
                [transaction_id],
            )
            row = cur.fetchone()
            if not row:
                missing_transactions.append(scenario)
                continue

            transaction_timestamp, transaction_context, velocity_snapshot = row
            context = transaction_context if isinstance(transaction_context, dict) else {}
            if transaction_timestamp < stale_cutoff:
                stale_transactions.append(scenario)
            if (
                context.get("seed_marker") != SEED_CONTEXT_MARKER
                or context.get("seed_scenario") != scenario
                or not context.get("seed_is_target")
            ):
                missing_context_markers.append(scenario)
            if scenario not in exempt_velocity and velocity_snapshot is None:
                missing_velocity_snapshots.append(scenario)

    quality_errors: list[str] = []
    if missing_transactions:
        quality_errors.append(
            f"missing target transactions: {', '.join(sorted(missing_transactions))}"
        )
    if stale_transactions:
        quality_errors.append(
            f"targets older than 72h window: {', '.join(sorted(stale_transactions))}"
        )
    if missing_context_markers:
        quality_errors.append(
            f"missing seed context markers: {', '.join(sorted(missing_context_markers))}"
        )
    if missing_velocity_snapshots:
        quality_errors.append(
            f"missing velocity_snapshot on target txn: {', '.join(sorted(missing_velocity_snapshots))}"
        )

    if quality_errors:
        joined = "; ".join(quality_errors)
        raise RuntimeError(f"Seed quality validation failed: {joined}")

    print(f"[SEED] Quality validation passed for {len(scenarios)} scenarios")


def insert_transaction(
    conn: psycopg.Connection,
    txn: dict,
) -> str:
    """Insert a test transaction and return its PK ID."""
    txn_id = txn["transaction_id"]
    card_id = txn["card_id"]
    merchant_id = txn["merchant_id"]

    # Convert dict values to JSON for JSONB columns
    # NOTE: velocity_results/velocity_snapshot must be dict or None (not list)
    # TM schema: dict[str, Any] | None — never store [] (list)
    transaction_context = json.dumps(txn.get("transaction_context") or {})
    velocity_snapshot = json.dumps(txn.get("velocity_snapshot") or None)
    velocity_results = json.dumps(txn.get("velocity_results") or None)

    # Handle empty decision_reason - default to DEFAULT_ALLOW for APPROVE
    decision_reason = txn.get("decision_reason", "DEFAULT_ALLOW")
    if not decision_reason or decision_reason == "":
        if txn.get("decision") == "APPROVE":
            decision_reason = "DEFAULT_ALLOW"
        else:
            decision_reason = "SYSTEM_DECLINE"

    # Default evaluation_type
    evaluation_type = txn.get("evaluation_type", "AUTH")

    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fraud_gov.transactions (
                id, transaction_id, evaluation_type, card_id, merchant_id, merchant_category_code,
                transaction_amount, transaction_currency, transaction_timestamp,
                decision, decision_reason, decision_score,
                transaction_context, velocity_snapshot, velocity_results,
                ingestion_source
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s
            )
            ON CONFLICT (transaction_id, transaction_timestamp, evaluation_type)
            DO UPDATE SET
                decision = EXCLUDED.decision,
                decision_reason = EXCLUDED.decision_reason,
                decision_score = EXCLUDED.decision_score
            RETURNING id
            """,
            [
                txn["id"],  # id (uuid)
                txn_id,  # transaction_id (uuid)
                evaluation_type,  # evaluation_type enum
                str(card_id),  # card_id (varchar)
                str(merchant_id),  # merchant_id (varchar)
                txn.get("merchant_category_code", "0000"),
                txn["amount"],
                txn.get("currency", "USD"),
                txn["timestamp"],
                txn.get("decision", "APPROVE"),
                decision_reason,
                txn.get("decision_score", 0.0),
                transaction_context,
                velocity_snapshot,
                velocity_results,
                "HTTP",  # ingestion_source — required by TM schema
            ],
        )
        return cur.fetchone()[0]


def insert_rule_match(
    conn: psycopg.Connection,
    transaction_pk_id: str,
    rule_name: str,
    action: str,
    score: float,
) -> None:
    """Insert a rule match for a transaction."""
    with conn.cursor() as cur:
        cur.execute(
            """
            INSERT INTO fraud_gov.transaction_rule_matches (
                transaction_id, rule_id, rule_name, rule_action, match_score,
                rule_output, matched, evaluated_at
            ) VALUES (
                %s, %s, %s, %s, %s, %s, %s, NOW()
            )
            ON CONFLICT DO NOTHING
            """,
            [
                transaction_pk_id,
                generate_uuid7(),  # rule_id (NOT NULL, use synthetic UUID)
                rule_name,
                action,
                score,
                json.dumps({"matched": True}),  # JSONB requires JSON string
                True,
            ],
        )


def seed_clear_fraud_card_testing(conn: psycopg.Connection) -> str:
    """Scenario: Card testing pattern - multiple small declines across merchants."""
    print("[SEED] Seeding CARD_TESTING_PATTERN scenario...")

    card_id = f"tok_cardtest_{generate_uuid7()[:8]}"  # Predictable card_id prefix
    base_time = datetime.now(UTC) - timedelta(hours=1)

    transactions = []
    # 6 attempts in a short window triggers velocity (>=0.6) and cross-merchant checks.
    for i in range(6):
        txn_uuid = generate_uuid7()  # Transaction ID must be valid UUID
        # Predictable merchant_id pattern for test discovery
        merchant_id = f"test-merchant-cardtest-{i}"

        txn = {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,  # Use valid UUID
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5399",  # Miscellaneous
            "amount": 1.99 + (i * 0.01),  # Small amounts
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 2),
            "decision": "DECLINE",  # decision_type enum
            "decision_reason": "VELOCITY_MATCH",  # decision_reason enum
            "decision_score": 0.95,
            "transaction_context": {"ip_country": "US", "3ds_verified": False},
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("card_testing_pattern", transactions)

    # Insert all transactions
    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        insert_rule_match(conn, pk_id, "CARD_TESTING_PATTERN", "DECLINE", 0.95)
        insert_rule_match(conn, pk_id, "VELOCITY_SHORT_TERM", "DECLINE", 0.85)

    # Return the last transaction_id for testing
    return transactions[-1]["transaction_id"]


def seed_clear_fraud_velocity(conn: psycopg.Connection) -> str:
    """Scenario: Velocity abuse — 5 transactions in 5 minutes, escalating amounts."""
    print("[SEED] Seeding VELOCITY_BURST scenario...")

    card_id = f"tok_velocity_{generate_uuid7()[:8]}"
    merchant_id = f"merchant_velocity_{generate_uuid7()[:8]}"
    base_time = datetime.now(UTC) - timedelta(minutes=10)

    transactions = []
    for i in range(5):
        txn_uuid = generate_uuid7()

        txn = {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_name": "Velocity Test Electronics",
            "merchant_category_code": "5732",  # Electronics
            "amount": 100.0 + (i * 200),  # Escalating: $100, $300, $500, $700, $900
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i),
            "decision": "DECLINE" if i >= 3 else "APPROVE",  # First 2 approved, then declines
            "decision_reason": "VELOCITY_MATCH" if i >= 3 else "DEFAULT_ALLOW",
            "decision_score": 0.7 + (i * 0.05),
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("clear_fraud_velocity", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["decision"] == "DECLINE":
            insert_rule_match(conn, pk_id, "VELOCITY_AMOUNT_THRESHOLD", "DECLINE", 0.88)
            insert_rule_match(conn, pk_id, "VELOCITY_FREQUENCY", "DECLINE", 0.92)

    return transactions[-1]["transaction_id"]


def seed_velocity_burst(conn: psycopg.Connection) -> str:
    """Scenario: Velocity burst — 12 transactions in 30 minutes (triggers 0.9 velocity score)."""
    print("[SEED] Seeding VELOCITY_BURST scenario (12 tx in 30min)...")

    card_id = f"tok_burst_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-velocityburst"
    # Use 10 minutes ago to ensure all transactions are recent when test runs
    base_time = datetime.now(UTC) - timedelta(minutes=10)

    transactions = []
    # 12 transactions spread over ~44 minutes - all within 1h window for test
    for i in range(12):
        txn_uuid = generate_uuid7()

        txn = {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5732",  # Electronics
            "amount": 50.0 + (i * 10),
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 4),  # Every 4 minutes
            "decision": "APPROVE" if i < 8 else "DECLINE",
            "decision_reason": "VELOCITY_MATCH" if i >= 8 else "DEFAULT_ALLOW",
            "decision_score": 0.5 + (i * 0.05),
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("velocity_burst", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["decision"] == "DECLINE":
            insert_rule_match(conn, pk_id, "VELOCITY_BURST_1H", "DECLINE", 0.92)

    return transactions[-1]["transaction_id"]


def seed_cross_merchant_spread(conn: psycopg.Connection) -> str:
    """Scenario: Cross-merchant spread — 11+ unique merchants in 24h (triggers 0.8 score)."""
    print("[SEED] Seeding CROSS_MERCHANT_SPREAD scenario (11 merchants in 24h)...")

    card_id = f"tok_cross_{generate_uuid7()[:8]}"
    # Use recent time to ensure transactions are within 24h window for test
    base_time = datetime.now(UTC) - timedelta(hours=2)

    transactions = []
    # 11 unique merchants = >10 threshold (score 0.8)
    # Use predictable merchant_id patterns for test discovery
    for i in range(11):
        txn_uuid = generate_uuid7()
        merchant_id = f"test-merchant-cross-{i}"  # Predictable pattern

        txn = {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5399",  # Miscellaneous
            "amount": 75.0 + (i * 5),
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 10),  # Spread over ~2 hours
            "decision": "APPROVE" if i < 8 else "DECLINE",
            "decision_reason": "VELOCITY_MATCH" if i >= 8 else "DEFAULT_ALLOW",
            "decision_score": 0.6 + (i * 0.03),
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("cross_merchant_spread", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["decision"] == "DECLINE":
            insert_rule_match(conn, pk_id, "CROSS_MERCHANT_PATTERN", "DECLINE", 0.82)

    return transactions[-1]["transaction_id"]


def seed_high_decline_ratio(conn: psycopg.Connection) -> str:
    """Scenario: High decline ratio — >50% decline rate (triggers 0.9 score)."""
    print("[SEED] Seeding HIGH_DECLINE_RATIO scenario (>50% decline rate)...")

    card_id = f"tok_decline_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-declineratio"
    # Use recent time to ensure transactions are within 24h window for test
    base_time = datetime.now(UTC) - timedelta(hours=2)

    transactions = []
    # 10 transactions: 6 declines (60% ratio) = >50% threshold (score 0.9)
    for i in range(10):
        txn_uuid = generate_uuid7()

        txn = {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5732",  # Electronics
            "amount": 150.0 + (i * 25),
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 10),  # Spread over ~2 hours
            "decision": "DECLINE" if i % 10 < 6 else "APPROVE",  # 6 declines, 4 approves
            "decision_reason": "VELOCITY_MATCH" if i % 10 < 6 else "DEFAULT_ALLOW",
            "decision_score": 0.7 + (0.05 if i % 10 < 6 else 0),
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("high_decline_ratio", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["decision"] == "DECLINE":
            insert_rule_match(conn, pk_id, "DECLINE_RATIO_ANOMALY", "DECLINE", 0.90)

    return transactions[-1]["transaction_id"]


def seed_legitimate_counter_evidence(conn: psycopg.Connection) -> str:
    """Scenario: Legitimate with counter-evidence — Declined but 3DS/trusted device (tests downgrade)."""
    print("[SEED] Seeding LEGITIMATE_WITH_COUNTER_EVIDENCE scenario...")

    card_id = f"tok_counter_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-counterevidence"
    txn_uuid = generate_uuid7()
    base_time = datetime.now(UTC) - timedelta(hours=6)

    transactions: list[dict[str, Any]] = []
    for i in range(4):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"test-merchant-counterevidence-prior-{i}",
                "merchant_category_code": "5411",
                "amount": 55.0 + (i * 12),
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.05,
                "transaction_context": {
                    "ip_country": "US",
                    "device_trusted": True,
                    "3ds_verified": True,
                    "cardholder_present": True,
                },
            }
        )

    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5411",  # Grocery - normally safe
            "amount": 250.00,  # Moderate amount
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=5),
            "decision": "DECLINE",  # Declined by rule engine but should be downgraded
            "decision_reason": "VELOCITY_MATCH",
            "decision_score": 0.65,
            "transaction_context": {
                "ip_country": "US",
                "device_trusted": True,  # Counter-evidence: trusted device
                "3ds_verified": True,  # Counter-evidence: 3DS success
                "cardholder_present": True,  # Counter-evidence: cardholder present
                "is_recurring_customer": True,  # Counter-evidence: known customer
            },
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("legitimate_counter_evidence", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["transaction_id"] == txn_uuid:
            insert_rule_match(conn, pk_id, "AMOUNT_THRESHOLD", "DECLINE", 0.65)

    return txn_uuid


def seed_likely_fraud(conn: psycopg.Connection) -> str:
    """Scenario: Likely fraud — new merchant, elevated amount, departure from card baseline.

    Seeds 5 prior normal transactions on the same card (grocery, $30-70 range)
    to establish a baseline, then a suspicious departure transaction at an
    entertainment merchant for $450 with an untrusted device.
    """
    print("[SEED] Seeding LIKELY_FRAUD scenario...")

    card_id = f"tok_likely_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-likelyfraud"
    txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(hours=6)
    transactions: list[dict[str, Any]] = []

    # Seed 5 prior normal transactions on this card (creates baseline for pattern engine)
    for i in range(5):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"test-merchant-likelyfraud-prior-{i}",
                "merchant_category_code": "5411",  # Grocery (normal baseline)
                "amount": 30.0 + (i * 10),  # Normal amounts: $30-$70
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.05,
                "transaction_context": {
                    "ip_country": "US",
                    "device_trusted": True,
                    "3ds_verified": True,
                },
                "velocity_snapshot": build_velocity_snapshot(
                    transaction_count_90d=i + 1,
                    approved_count_90d=i + 1,
                    velocity_24h=i + 1,
                ),
            }
        )

    # Target transaction: suspicious departure from baseline
    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "7999",  # Entertainment - departure from grocery baseline
            "amount": 450.00,  # ~6x the card's average ($50 avg from prior txns)
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=5),
            "decision": "DECLINE",
            "decision_reason": "VELOCITY_MATCH",
            "decision_score": 0.65,
            "transaction_context": {
                "ip_country": "US",
                "device_trusted": False,  # New device
                "3ds_verified": False,
            },
            "velocity_snapshot": {
                "velocity_24h": 6,
                "transaction_count_90d": 6,
                "approval_rate_90d": 0.83,
            },
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("likely_fraud", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["transaction_id"] == txn_uuid:
            insert_rule_match(conn, pk_id, "NEW_MERCHANT_ELEVATED_AMOUNT", "DECLINE", 0.65)

    return txn_uuid


def seed_legitimate(conn: psycopg.Connection) -> str:
    """Scenario: Legitimate transaction — normal patterns, trusted merchant, 3DS success."""
    print("[SEED] Seeding LEGITIMATE scenario...")

    card_id = f"tok_legit_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-legitimate"
    txn_uuid = generate_uuid7()
    base_time = datetime.now(UTC) - timedelta(hours=6)
    transactions: list[dict[str, Any]] = []
    for i in range(5):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"test-merchant-legitimate-prior-{i}",
                "merchant_category_code": "5411",
                "amount": 42.0 + (i * 8),
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.03,
                "transaction_context": {
                    "ip_country": "US",
                    "device_trusted": True,
                    "3ds_verified": True,
                    "cardholder_present": True,
                },
            }
        )

    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5411",  # Grocery
            "amount": 85.50,
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=2),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.05,
            "transaction_context": {
                "ip_country": "US",
                "device_trusted": True,
                "3ds_verified": True,
                "cardholder_present": True,
            },
            "velocity_snapshot": build_velocity_snapshot(
                transaction_count_90d=6,
                approved_count_90d=6,
                velocity_24h=6,
            ),
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("legitimate", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_approved_likely_fraud(conn: psycopg.Connection) -> str:
    """Scenario: Approved but likely fraud - high amount APPROVE with suspicious indicators.

    This tests the pipeline's ability to flag transactions as suspicious even when
    the rule engine approved them (false negative from rule engine).

    Seeds 4 prior normal transactions on the same card to establish a baseline,
    then a suspicious $750 electronics purchase with untrusted device and no 3DS.
    """
    print("[SEED] Seeding APPROVED_LIKELY_FRAUD scenario...")

    card_id = f"tok_approved_fraud_{generate_uuid7()[:8]}"
    # Predictable merchant_id pattern for test discovery
    merchant_id = "test-merchant-approvedfraud"
    txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(hours=8)
    transactions: list[dict[str, Any]] = []

    # Seed 4 prior normal transactions on this card (creates baseline)
    for i in range(4):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"test-merchant-approvedfraud-prior-{i}",
                "merchant_category_code": "5411",  # Grocery (normal baseline)
                "amount": 25.0 + (i * 15),  # Normal amounts: $25-$70
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i * 2),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.05,
                "transaction_context": {
                    "ip_country": "US",
                    "device_trusted": True,
                    "3ds_verified": True,
                },
                "velocity_snapshot": build_velocity_snapshot(
                    transaction_count_90d=i + 1,
                    approved_count_90d=i + 1,
                    velocity_24h=i + 1,
                ),
            }
        )

    # Target transaction: approved despite suspicious signals
    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5732",  # Electronics - departure from grocery baseline
            "amount": 750.00,  # ~15x the card's average ($50 avg from prior txns)
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=8),
            "decision": "APPROVE",  # Approved by rule engine (false negative)
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.35,  # Elevated but below decline threshold
            "transaction_context": {
                "ip_country": "US",
                "device_trusted": False,  # Suspicious: untrusted device
                "3ds_verified": False,  # Suspicious: no 3DS
                "cardholder_present": False,
                "is_new_merchant": True,  # Suspicious: first time at this merchant
            },
            "velocity_snapshot": {
                "velocity_24h": 5,
                "transaction_count_90d": 5,
                "approval_rate_90d": 1.0,  # All prior were approvals
            },
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("approved_likely_fraud", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)
    # No rule match means it was approved by default - the pipeline should catch this

    return txn_uuid


def seed_edge_first_transaction(conn: psycopg.Connection) -> str:
    """Scenario: First transaction on a new card — no history."""
    print("[SEED] Seeding EDGE_FIRST_TRANSACTION scenario...")

    card_id = f"tok_first_{generate_uuid7()[:8]}"
    merchant_id = f"merchant_retail_{generate_uuid7()[:8]}"
    txn_uuid = generate_uuid7()

    txn = {
        "id": generate_uuid7(),
        "transaction_id": txn_uuid,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "merchant_name": "Retail Store",
        "merchant_category_code": "5311",  # Department stores
        "amount": 125.00,
        "currency": "USD",
        "timestamp": datetime.now(UTC) - timedelta(minutes=1),
        "decision": "APPROVE",
        "decision_reason": "DEFAULT_ALLOW",
        "decision_score": 0.15,
        "transaction_context": {
            "ip_country": "US",
            "3ds_verified": True,
        },
        "velocity_snapshot": build_velocity_snapshot(
            transaction_count_90d=1,
            approved_count_90d=1,
            velocity_24h=1,
        ),
    }

    with_seed_context(txn, scenario="edge_first_transaction", sequence=1, is_target=True)
    insert_transaction(conn, txn)

    return txn_uuid


def seed_edge_missing_data(conn: psycopg.Connection) -> str:
    """Scenario: Transaction with missing optional fields."""
    print("[SEED] Seeding EDGE_MISSING_DATA scenario...")

    card_id = f"tok_missing_{generate_uuid7()[:8]}"
    merchant_id = f"merchant_unknown_{generate_uuid7()[:8]}"
    txn_uuid = generate_uuid7()
    base_time = datetime.now(UTC) - timedelta(hours=4)
    transactions: list[dict[str, Any]] = []

    for i in range(2):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"{merchant_id}-prior-{i}",
                "merchant_name": "Known Merchant",
                "merchant_category_code": "5411",
                "amount": 48.0 + (i * 4),
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.08,
                "transaction_context": {"ip_country": "US", "3ds_verified": True},
            }
        )

    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_name": "Unknown Merchant",
            "merchant_category_code": "9999",  # Unknown
            "amount": 50.00,
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=3),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.10,
            "transaction_context": {},  # Empty context by design
            "velocity_snapshot": None,  # Missing by design
            "velocity_results": None,
        }
    )

    apply_velocity_snapshots(transactions[:-1])
    annotate_scenario_transactions("edge_missing_data", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_amount_round_number(conn: psycopg.Connection) -> str:
    """Scenario: Amount anomaly - round number ($500) - common fraud amount."""
    print("[SEED] Seeding AMOUNT_ROUND_NUMBER scenario (round number $500)...")

    card_id = f"tok_round_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-round"
    txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(hours=2)

    transactions = []
    for i in range(5):
        txn = {
            "id": generate_uuid7(),
            "transaction_id": generate_uuid7(),
            "card_id": card_id,
            "merchant_id": f"{merchant_id}-{i}",
            "merchant_category_code": "5411",
            "amount": 50.0 + (i * 10),
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 15),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.1,
            "transaction_context": {"ip_country": "US", "3ds_verified": True},
        }
        transactions.append(txn)

    final_txn = {
        "id": generate_uuid7(),
        "transaction_id": txn_uuid,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "merchant_category_code": "5732",
        "amount": 500.0,
        "currency": "USD",
        "timestamp": datetime.now(UTC) - timedelta(minutes=5),
        "decision": "APPROVE",
        "decision_reason": "DEFAULT_ALLOW",
        "decision_score": 0.3,
        "transaction_context": {"ip_country": "US"},
    }
    transactions.append(final_txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("amount_round_number", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_amount_high(conn: psycopg.Connection) -> str:
    """Scenario: Amount anomaly - high amount ($1500)."""
    print("[SEED] Seeding AMOUNT_HIGH scenario (high amount $1500)...")

    card_id = f"tok_highamt_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-highamt"
    txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(hours=3)

    transactions = []
    for i in range(8):
        txn = {
            "id": generate_uuid7(),
            "transaction_id": generate_uuid7(),
            "card_id": card_id,
            "merchant_id": f"{merchant_id}-{i}",
            "merchant_category_code": "5411",
            "amount": 40.0 + (i * 5),
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 20),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.05,
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    final_txn = {
        "id": generate_uuid7(),
        "transaction_id": txn_uuid,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "merchant_category_code": "5947",
        "amount": 1500.0,
        "currency": "USD",
        "timestamp": datetime.now(UTC) - timedelta(minutes=5),
        "decision": "APPROVE",
        "decision_reason": "DEFAULT_ALLOW",
        "decision_score": 0.4,
        "transaction_context": {"ip_country": "US"},
    }
    transactions.append(final_txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("amount_high", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_time_unusual_hour(conn: psycopg.Connection) -> str:
    """Scenario: Time anomaly - unusual hour (3 AM)."""
    print("[SEED] Seeding TIME_UNUSUAL_HOUR scenario (3 AM transaction)...")

    card_id = f"tok_latenight_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-latenight"
    txn_uuid = generate_uuid7()

    transactions = []
    # Use relative timestamps within the 72h window so the pattern engine sees them
    base_time = datetime.now(UTC) - timedelta(hours=12)
    for i in range(4):
        txn = {
            "id": generate_uuid7(),
            "transaction_id": generate_uuid7(),
            "card_id": card_id,
            "merchant_id": f"{merchant_id}-{i}",
            "merchant_category_code": "5541",
            "amount": 40.0 + (i * 5),
            "currency": "USD",
            "timestamp": base_time + timedelta(hours=i * 2),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.05,
            "transaction_context": {"ip_country": "US"},
        }
        transactions.append(txn)

    # Target transaction at 3 AM today (unusual hour)
    today_3am = datetime.now(UTC).replace(hour=3, minute=15, second=0, microsecond=0)
    # If 3 AM hasn't happened yet today, use yesterday's 3 AM
    if today_3am > datetime.now(UTC):
        today_3am -= timedelta(days=1)

    final_txn = {
        "id": generate_uuid7(),
        "transaction_id": txn_uuid,
        "card_id": card_id,
        "merchant_id": merchant_id,
        "merchant_category_code": "7999",
        "amount": 250.0,
        "currency": "USD",
        "timestamp": today_3am,
        "decision": "APPROVE",
        "decision_reason": "DEFAULT_ALLOW",
        "decision_score": 0.35,
        "transaction_context": {"ip_country": "US"},
    }
    transactions.append(final_txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("time_unusual_hour", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_timezone_mismatch(conn: psycopg.Connection) -> str:
    """Scenario: Time anomaly - timezone mismatch (IP country different from card country)."""
    print("[SEED] Seeding TIMEZONE_MISMATCH scenario...")

    card_id = f"tok_tz_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-tz"
    txn_uuid = generate_uuid7()
    base_time = datetime.now(UTC) - timedelta(hours=8)
    transactions: list[dict[str, Any]] = []
    for i in range(3):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"{merchant_id}-prior-{i}",
                "merchant_category_code": "5812",
                "amount": 65.0 + (i * 15),
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i * 2),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.08,
                "transaction_context": {
                    "ip_country": "US",
                    "card_country": "US",
                },
            }
        )

    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5812",
            "amount": 350.0,
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=5),
            "decision": "APPROVE",
            "decision_reason": "DEFAULT_ALLOW",
            "decision_score": 0.25,
            "transaction_context": {
                "ip_country": "CN",
                "card_country": "US",
            },
            "velocity_snapshot": build_velocity_snapshot(
                transaction_count_90d=4,
                approved_count_90d=4,
                velocity_24h=4,
            ),
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("timezone_mismatch", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_counter_evidence_extended(conn: psycopg.Connection) -> str:
    """Scenario: Extended counter-evidence - AVS, CVV, tokenized payment."""
    print("[SEED] Seeding COUNTER_EVIDENCE_EXTENDED scenario...")

    card_id = f"tok_extcounter_{generate_uuid7()[:8]}"
    merchant_id = "test-merchant-extcounter"
    txn_uuid = generate_uuid7()
    base_time = datetime.now(UTC) - timedelta(hours=6)
    transactions: list[dict[str, Any]] = []
    for i in range(3):
        transactions.append(
            {
                "id": generate_uuid7(),
                "transaction_id": generate_uuid7(),
                "card_id": card_id,
                "merchant_id": f"{merchant_id}-prior-{i}",
                "merchant_category_code": "5411",
                "amount": 60.0 + (i * 20),
                "currency": "USD",
                "timestamp": base_time + timedelta(hours=i),
                "decision": "APPROVE",
                "decision_reason": "DEFAULT_ALLOW",
                "decision_score": 0.08,
                "transaction_context": {
                    "ip_country": "US",
                    "avs_match": True,
                    "cvv_match": True,
                    "3ds_verified": True,
                    "device_trusted": True,
                },
            }
        )

    transactions.append(
        {
            "id": generate_uuid7(),
            "transaction_id": txn_uuid,
            "card_id": card_id,
            "merchant_id": merchant_id,
            "merchant_category_code": "5411",
            "amount": 200.0,
            "currency": "USD",
            "timestamp": datetime.now(UTC) - timedelta(minutes=5),
            "decision": "DECLINE",
            "decision_reason": "VELOCITY_MATCH",
            "decision_score": 0.65,
            "transaction_context": {
                "ip_country": "US",
                "avs_match": True,
                "avs_response": "Y",
                "cvv_match": True,
                "cvv_response": "Y",
                "is_tokenized": True,
                "payment_token_present": True,
                "3ds_verified": True,
                "device_trusted": True,
                "is_known_merchant": True,
            },
        }
    )

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("counter_evidence_extended", transactions)

    for txn in transactions:
        insert_transaction(conn, txn)

    return txn_uuid


def seed_card_testing_sequence(conn: psycopg.Connection) -> str:
    """Scenario: Card testing - increasing amounts sequence."""
    print("[SEED] Seeding CARD_TESTING_SEQUENCE scenario...")

    card_id = f"tok_cardtestseq_{generate_uuid7()[:8]}"
    final_txn_uuid = generate_uuid7()

    base_time = datetime.now(UTC) - timedelta(minutes=30)

    amounts = [1.0, 5.0, 10.0, 15.0, 20.0, 25.0]
    transactions = []

    for i, amount in enumerate(amounts):
        is_final = i == len(amounts) - 1
        tx_count = i + 1
        approved_count = 1 if is_final else 0
        txn = {
            "id": generate_uuid7(),
            "transaction_id": final_txn_uuid if is_final else generate_uuid7(),
            "card_id": card_id,
            "merchant_id": f"test-merchant-ct-{i}",
            "merchant_category_code": "5999",
            "amount": amount,
            "currency": "USD",
            "timestamp": base_time + timedelta(minutes=i * 5),
            "decision": "APPROVE" if is_final else "DECLINE",
            "decision_reason": "DEFAULT_ALLOW" if is_final else "VELOCITY_MATCH",
            "decision_score": 0.3 if is_final else 0.8,
            "transaction_context": {"ip_country": "US", "3ds_verified": False},
            "velocity_snapshot": {
                "velocity_24h": tx_count,
                "transaction_count_90d": tx_count,
                "approval_rate_90d": round(approved_count / tx_count, 2),
            },
        }
        transactions.append(txn)

    apply_velocity_snapshots(transactions)
    annotate_scenario_transactions("card_testing_sequence", transactions)

    for txn in transactions:
        pk_id = insert_transaction(conn, txn)
        if txn["decision"] == "DECLINE":
            insert_rule_match(conn, pk_id, "CARD_TESTING_SEQUENCE", "DECLINE", 0.80)

    return final_txn_uuid


def main() -> None:
    """Seed all test scenarios."""
    print("\n=== Seeding Test Scenario Data ===\n")

    with psycopg.connect(DATABASE_URL) as conn:
        clear_test_data(conn)

        scenarios = {}
        scenarios["card_testing_pattern"] = seed_clear_fraud_card_testing(conn)
        conn.commit()
        scenarios["velocity_burst"] = seed_velocity_burst(conn)
        conn.commit()
        scenarios["cross_merchant_spread"] = seed_cross_merchant_spread(conn)
        conn.commit()
        scenarios["high_decline_ratio"] = seed_high_decline_ratio(conn)
        conn.commit()
        scenarios["legitimate_counter_evidence"] = seed_legitimate_counter_evidence(conn)
        conn.commit()
        scenarios["clear_fraud_velocity"] = seed_clear_fraud_velocity(conn)
        conn.commit()
        scenarios["likely_fraud"] = seed_likely_fraud(conn)
        conn.commit()
        scenarios["legitimate"] = seed_legitimate(conn)
        conn.commit()
        scenarios["approved_likely_fraud"] = seed_approved_likely_fraud(conn)
        conn.commit()
        scenarios["edge_first_transaction"] = seed_edge_first_transaction(conn)
        conn.commit()
        scenarios["edge_missing_data"] = seed_edge_missing_data(conn)
        conn.commit()

        scenarios["amount_round_number"] = seed_amount_round_number(conn)
        conn.commit()
        scenarios["amount_high"] = seed_amount_high(conn)
        conn.commit()
        scenarios["time_unusual_hour"] = seed_time_unusual_hour(conn)
        conn.commit()
        scenarios["timezone_mismatch"] = seed_timezone_mismatch(conn)
        conn.commit()
        scenarios["counter_evidence_extended"] = seed_counter_evidence_extended(conn)
        conn.commit()
        scenarios["card_testing_sequence"] = seed_card_testing_sequence(conn)
        conn.commit()
        validate_seed_quality(conn, scenarios)
        write_seed_manifest(scenarios)

    # Print summary outside the connection context
    print("\n=== Test Data Summary ===")
    for name, txn_id in scenarios.items():
        print(f"  {name}: {txn_id}")

    print("\nSeeding complete!")
    print("\nTo test specific scenarios:")
    print("  uv run pytest tests/e2e/test_scenarios.py -v")
    print(f"  manifest: {SEED_MANIFEST_PATH}")


if __name__ == "__main__":
    main()
