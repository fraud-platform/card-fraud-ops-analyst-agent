# Testing Strategy

## Overview

Testing is organized into four layers:

- `tests/unit`: deterministic and fast, no external services.
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
uv run pytest tests/integration -v
uv run pytest tests/e2e -v
```

## Current Validation Baseline (2026-02-16)

- Lint: passing (`ruff check`)
- Format: passing (`ruff format --check`)
- Unit + smoke: passing in local verification
- Integration: conditionally executed (DB/test config dependent)
- E2E: deterministic scenario suite with seed manifest + acceptance KPI gate

## Coverage

Generate HTML coverage:

```bash
uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch
```

Open `htmlcov/index.html` in a browser for line/branch coverage review.

## Test Layer Notes

### Unit

- No real DB or LLM dependencies.
- Primary place to validate deterministic logic, repositories (mocked), and service orchestration.
- `tests/conftest.py` sets `SECURITY_SKIP_JWT_VALIDATION=true` for test-only auth bypass.

### Smoke

- Uses `TestClient`; validates endpoint registration, auth wiring, and response shape.
- Should remain fast and stable for frequent local/CI runs.

### Integration

- Requires reachable DB and valid test configuration/secrets.
- Should be skipped, not failed, when required DB config is intentionally unavailable.

### E2E

- Requires running Ops Agent + Transaction Management services and seeded data.
- Seed scenarios with `scripts/seed_test_scenarios.py` before running the suite.
- Seed manifest (`htmlcov/e2e-seed-manifest.json`) is used for deterministic scenario transaction selection.
- Validates scenario outcomes, worklist behavior, and acknowledgement flow.
- Enforces acceptance KPI thresholds (`test_acceptance_kpi_gate`) for fraud recall, low-risk precision, recommendation coverage, and latency p95.
- `fraud_recall_medium_plus` is measured on high-confidence fraud seeds (card testing, velocity burst, cross-merchant spread, high-decline ratio), not mixed/advisory fraud scenarios.
- Scenario assertions should focus on stable invariants (severity floor, recommendation behavior, response contracts) to avoid environment-specific false negatives.
- HTML report `evidence_summary` is derived from `evidence_payload`; if no evidence is returned by API the field is intentionally `[]`.

## CI Guidance

- Run lint + format + unit + smoke on every push/PR.
- Run integration on DB-enabled pipelines.
- Run e2e before release or when changing orchestration, persistence contracts, or API behavior.
