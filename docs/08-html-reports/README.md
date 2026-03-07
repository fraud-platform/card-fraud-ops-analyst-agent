# HTML Reports

Latest E2E HTML artifacts:

- e2e-31matrix-report-20260307-111513.html
- e2e-pytest-report-20260307-065729.html

Source commands:

`doppler run --project card-fraud-platform --config local -- uv run python scripts/run_e2e_matrix_detailed.py`
`doppler run --project card-fraud-platform --config local -- uv run pytest tests/e2e/test_scenarios.py -v --tb=short -s --html=htmlcov/e2e-pytest-report.html --self-contained-html`
