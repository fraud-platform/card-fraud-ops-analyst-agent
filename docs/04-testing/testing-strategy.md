# Testing Strategy

## Overview

Testing is organized into four layers:

- `tests/unit`: predictable and fast, no external services.
- `tests/smoke`: API contract checks with FastAPI `TestClient`.
- `tests/integration`: database-backed checks when DB/test config is available.
- `tests/e2e`: live end-to-end scenarios against running services.

All merges must keep lint and format clean and required test suites passing.

## Required Quality Gates

```bash
uv run ruff check app/ tests/ cli/ scripts/
uv run ruff format --check app/ tests/ cli/ scripts/
uv run pytest tests/unit -v
uv run pytest tests/smoke -v
```

Integration and e2e are required for release validation when the environment is available:

```bash
doppler run --config local-test -- uv run pytest tests/integration -v
uv run pytest tests/e2e -v
```

If `local-test` is not available, use:

```bash
doppler run --config local -- uv run pytest tests/integration -v
```

## Validation Expectations

- Lint + format must pass before merge.
- Unit + smoke are required on every change.
- Integration runs when DB/test config is available.
- E2E runs are required before release and for orchestration/tooling changes.

## Coverage

Generate HTML coverage:

```bash
uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch
```

Open `htmlcov/index.html` in a browser for line/branch coverage review.

## Test Layer Notes

### Unit

- No real DB or LLM dependencies.
- Primary place to validate rule/policy logic, repositories (mocked), and service orchestration.
- `tests/conftest.py` sets `SECURITY_SKIP_JWT_VALIDATION=true` for test-only auth bypass.

### Smoke

- Uses `TestClient`; validates endpoint registration, auth wiring, and response shape.
- Should remain fast and stable for frequent local/CI runs.

### Integration

- Requires reachable DB and valid test configuration/secrets.
- Should be skipped, not failed, when required DB config is intentionally unavailable.

### E2E

- Requires running Ops Agent + Transaction Management services and seeded data.
- Local Docker dependencies must be healthy on `localhost:8002` (TM) and `localhost:8003` (Ops Agent).
- Always rebuild/recreate `ops-analyst-agent` before final E2E verification to avoid stale-image false negatives.
- Seed scenarios with `scripts/seed_test_scenarios.py` before running the suite.
- Seed manifest (`htmlcov/e2e-seed-manifest.json`) is used for stable scenario transaction selection.
- Validates scenario outcomes, worklist behavior, and acknowledgement flow.
- Enforces acceptance KPI thresholds (`test_acceptance_kpi_gate`) for fraud recall, low-risk precision, recommendation coverage, and latency p95.
- `fraud_recall_medium_plus` is measured on high-confidence fraud seeds (card testing, velocity burst, cross-merchant spread, high-decline ratio), not mixed/advisory fraud scenarios.
- Scenario assertions should focus on stable invariants (severity floor, recommendation behavior, response contracts) to avoid environment-specific false negatives.
- HTML report `evidence_summary` is derived from `evidence_payload`; if no evidence is returned by API the field is intentionally `[]`.
- `scripts/docker_guard.py` preflight enforces local Docker target correctness, TM dependency readiness, and stale-container detection before scenario execution.

## CI Guidance

- Run lint + format + unit + smoke on every push/PR.
- Run integration on DB-enabled pipelines.
- Run e2e before release or when changing orchestration, persistence contracts, or API behavior.
