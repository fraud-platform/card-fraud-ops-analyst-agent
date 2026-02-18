"""Seed test data for integration and e2e testing.

Inserts into ops_agent_* tables only (transactions are owned by TM).
Picks the first N real transaction UUIDs from fraud_gov.transactions that
have at least one rule match — these are the interesting high-signal cases.

Run via Doppler:
    uv run db-load-test-data

Idempotent: Running twice will skip already-inserted rows (ON CONFLICT DO NOTHING).
"""

import asyncio
import json
import logging
import os
import sys
import uuid
from datetime import UTC, datetime, timedelta

logger = logging.getLogger(__name__)

NOW = datetime.now(UTC)


async def load_test_data() -> None:
    """Insert all seed data idempotently."""
    from sqlalchemy.ext.asyncio import create_async_engine

    from app.core.config import to_asyncpg_url

    database_url = os.environ.get("DATABASE_URL_APP")
    if not database_url:
        logger.error(
            "DATABASE_URL_APP not set. Run via Doppler: "
            "doppler run -- python -m scripts.load_test_data"
        )
        sys.exit(1)

    database_url = to_asyncpg_url(database_url)
    engine = create_async_engine(database_url)

    async with engine.begin() as conn:
        txn_ids = await _pick_transactions(conn)
        if not txn_ids:
            logger.warning("No transactions with rule matches found — seed skipped.")
            logger.warning("Run the transaction-management service to generate transactions first.")
            await engine.dispose()
            return

        await _seed_ops_agent_data(conn, txn_ids)

    await engine.dispose()

    logger.info("=" * 60)
    logger.info("Test data loaded. Transaction IDs available for testing:")
    for txn_id in txn_ids:
        logger.info("  %s", txn_id)
    logger.info("")
    logger.info(
        "Set env var for load testing:\n  OPS_ANALYST_TRANSACTION_IDS=%s",
        ",".join(str(t) for t in txn_ids),
    )
    logger.info("=" * 60)


async def _pick_transactions(conn) -> list[str]:
    """Find up to 10 real transaction UUIDs that have rule matches (high-signal)."""
    from sqlalchemy import text

    result = await conn.execute(
        text("""
            SELECT DISTINCT t.transaction_id::text AS transaction_id
            FROM fraud_gov.transactions t
            JOIN fraud_gov.transaction_rule_matches trm ON trm.transaction_id = t.id
            WHERE trm.matched = TRUE
            ORDER BY transaction_id
            LIMIT 10
        """)
    )
    rows = result.fetchall()
    if not rows:
        # Fall back to any transactions with DECLINE decision
        result = await conn.execute(
            text("""
                SELECT transaction_id::text
                FROM fraud_gov.transactions
                WHERE decision = 'DECLINE'
                ORDER BY transaction_timestamp DESC
                LIMIT 10
            """)
        )
        rows = result.fetchall()
    return [row[0] for row in rows]


async def _seed_ops_agent_data(conn, txn_ids: list[str]) -> None:
    """Insert ops_agent_runs, insights, evidence, and recommendations."""
    from sqlalchemy import text

    logger.info("Seeding ops_agent_* tables for %d transactions ...", len(txn_ids))

    seeded_runs = 0
    seeded_insights = 0
    seeded_recs = 0

    for txn_id in txn_ids:
        # Fetch the PK (id) for this transaction
        result = await conn.execute(
            text(
                "SELECT id, decision, decision_score, risk_level, card_id, merchant_id "
                "FROM fraud_gov.transactions WHERE transaction_id = :txn_id"
            ),
            {"txn_id": txn_id},
        )
        txn_row = result.fetchone()
        if txn_row is None:
            logger.warning("  Transaction not found: %s — skipping", txn_id)
            continue

        txn_pk_id = str(txn_row[0])
        decision = str(txn_row[1]) if txn_row[1] else "DECLINE"
        decision_score = float(txn_row[2]) if txn_row[2] else 0.5
        risk_level = str(txn_row[3]) if txn_row[3] else "MEDIUM"

        # Get rule matches for this transaction
        result = await conn.execute(
            text("""
                SELECT rule_name, rule_action, match_score, rule_output
                FROM fraud_gov.transaction_rule_matches
                WHERE transaction_id = :txn_pk AND matched = TRUE
                ORDER BY match_score DESC NULLS LAST
                LIMIT 5
            """),
            {"txn_pk": txn_pk_id},
        )
        rule_matches = [dict(r._mapping) for r in result.fetchall()]

        # ---- Run ----
        run_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"seed-run-{txn_id}"))
        await conn.execute(
            text("""
                INSERT INTO fraud_gov.ops_agent_runs
                    (run_id, mode, trigger_ref, started_at, completed_at, status)
                VALUES
                    (:run_id, 'quick', :trigger_ref, :started_at, :completed_at, 'SUCCESS')
                ON CONFLICT (run_id) DO NOTHING
            """),
            {
                "run_id": run_id,
                "trigger_ref": f"transaction:{txn_id}",
                "started_at": NOW - timedelta(minutes=5),
                "completed_at": NOW - timedelta(minutes=4, seconds=30),
            },
        )
        seeded_runs += 1

        # ---- Insight ----
        insight_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"seed-insight-{txn_id}"))
        idempotency_insight = f"seed:insight:{txn_id}"
        severity = _score_to_severity(decision_score)
        summary = (
            f"Seeded insight: decision={decision}, score={decision_score:.2f}, "
            f"risk={risk_level}, rules_matched={len(rule_matches)}"
        )
        await conn.execute(
            text("""
                INSERT INTO fraud_gov.ops_agent_insights
                    (insight_id, transaction_pk_id, transaction_id, severity,
                     insight_summary, insight_type, generated_at, model_mode, idempotency_key)
                VALUES
                    (:insight_id, :txn_pk_id, :txn_id, :severity,
                     :summary, 'pattern_analysis', :generated_at, 'deterministic', :idempotency_key)
                ON CONFLICT (idempotency_key) DO NOTHING
            """),
            {
                "insight_id": insight_id,
                "txn_pk_id": txn_pk_id,
                "txn_id": txn_id,
                "severity": severity,
                "summary": summary,
                "generated_at": NOW - timedelta(minutes=4),
                "idempotency_key": idempotency_insight,
            },
        )
        seeded_insights += 1

        # ---- Evidence (one item per rule match, up to 3) ----
        for match in rule_matches[:3]:
            pattern = _rule_name_to_pattern(str(match["rule_name"]))
            ev_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"seed-ev-{txn_id}-{match['rule_name']}"))
            await conn.execute(
                text("""
                    INSERT INTO fraud_gov.ops_agent_evidence
                        (evidence_id, insight_id, evidence_kind, evidence_payload, created_at)
                    VALUES
                        (:ev_id, :insight_id, :kind, :payload, :created_at)
                    ON CONFLICT (evidence_id) DO NOTHING
                """),
                {
                    "ev_id": ev_id,
                    "insight_id": insight_id,
                    "kind": pattern,
                    "payload": json.dumps(
                        {
                            "pattern_name": pattern,
                            "score": float(match["match_score"]) if match["match_score"] else 0.5,
                            "rule_name": match["rule_name"],
                            "rule_action": str(match["rule_action"])
                            if match["rule_action"]
                            else None,
                        }
                    ),
                    "created_at": NOW - timedelta(minutes=4),
                },
            )

        # ---- Recommendation ----
        rec_id = str(uuid.uuid5(uuid.NAMESPACE_DNS, f"seed-rec-{txn_id}"))
        idempotency_rec = f"seed:rec:{txn_id}"
        rec_type = "rule_candidate" if decision_score >= 0.75 else "manual_review"
        await conn.execute(
            text("""
                INSERT INTO fraud_gov.ops_agent_recommendations
                    (recommendation_id, insight_id, recommendation_type,
                     recommendation_payload, status, idempotency_key, created_at)
                VALUES
                    (:rec_id, :insight_id, :rec_type,
                     :payload, 'OPEN', :idempotency_key, :created_at)
                ON CONFLICT (idempotency_key) DO NOTHING
            """),
            {
                "rec_id": rec_id,
                "insight_id": insight_id,
                "rec_type": rec_type,
                "payload": json.dumps(
                    {
                        "title": f"Seed recommendation ({rec_type}) for {txn_id[:8]}...",
                        "impact": f"High-confidence {decision} signal — review for rule update",
                        "priority": 1 if severity == "HIGH" else 2,
                    }
                ),
                "idempotency_key": idempotency_rec,
                "created_at": NOW - timedelta(minutes=3),
            },
        )
        seeded_recs += 1

    logger.info(
        "  Seeded %d runs, %d insights, %d recommendations.",
        seeded_runs,
        seeded_insights,
        seeded_recs,
    )


def _score_to_severity(score: float) -> str:
    if score >= 0.80:
        return "HIGH"
    if score >= 0.50:
        return "MEDIUM"
    return "LOW"


def _rule_name_to_pattern(rule_name: str) -> str:
    name = rule_name.lower()
    if "velocity" in name:
        return "velocity"
    if "geo" in name or "location" in name:
        return "geo_improbable"
    if "amount" in name or "spike" in name:
        return "amount_anomaly"
    if "decline" in name:
        return "decline_anomaly"
    if "card" in name:
        return "card_risk"
    return "pattern_signal"


if __name__ == "__main__":
    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s [%(levelname)s] %(message)s",
    )
    asyncio.run(load_test_data())
