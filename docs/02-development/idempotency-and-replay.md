# Idempotency and Replay

## Objective

Guarantee deterministic and non-duplicative agent artifacts under retries, restarts, and reprocessing.

## Idempotency Keys

### Insight generation key

`(transaction_id, evaluation_type, transaction_timestamp, insight_type, model_mode)`

### Recommendation key

`(insight_id, recommendation_type, recommendation_signature_hash)`

### Rule draft key

`(recommendation_id, draft_package_version)`

## Replay Modes

- `single-transaction replay`: re-run one transaction by ID.
- `window replay`: rerun a bounded time window for calibration.
- `policy replay`: rerun after threshold or policy updates.

## Replay Rules

- Replays create new run records but should not duplicate unchanged insights.
- Changed outputs must retain lineage back to source run and policy version.
- Rejected recommendations are never silently reopened by replay.

## Failure Handling

- Partial failures record `PARTIAL` run status with phase-level error metadata.
- Retryable phases should be retried with exponential backoff.
- Non-retryable failures must emit operator alerts and audit events.
