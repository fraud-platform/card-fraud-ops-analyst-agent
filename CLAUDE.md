# CLAUDE.md

All agent instructions live in **AGENTS.md** — the single source of truth for this repository.

Read `AGENTS.md` before making any changes. It contains:
- Quality gates (lint, format, unit tests, smoke tests, integration tests)
- No-shortcuts policy
- Tooling rules (uv only, Doppler only, no pip, no .env)
- Database isolation rules (ops_agent_* tables only, never drop fraud_gov schema)
- Architecture guardrails and coding standards
- Phase 1 implementation plan and checklist
- Project structure and naming conventions

## Quick Reference

```bash
# Quality gates (must all pass; run commands for current suite counts)
uv run ruff check app/ tests/ cli/ scripts/           # Lint
uv run ruff format --check app/ tests/ cli/ scripts/  # Format
uv run pytest tests/unit -v                            # Unit tests
uv run pytest tests/smoke -v                           # Smoke tests

# Pre-commit hooks (enforce quality gates before commit)
uv run pre-commit install                               # Install hooks (one-time)
uv run pre-commit run --all-files                       # Run manually on all files
uv run pre-commit autoupdate                            # Update hook versions

# HTML test coverage report
uv run pytest tests/ --html=htmlcov/index.html --self-contained-html --cov=app --cov-report=html:htmlcov --cov-branch

# Development (always via Doppler)
uv run doppler-local                                   # Dev server with secrets
uv run doppler-local-test                              # Tests with local DB

# Auth0 setup (one-time)
uv run auth0-bootstrap --yes --verbose                 # Bootstrap Auth0 API + M2M
uv run auth0-verify                                    # Verify Auth0 config

# Database (this project's tables ONLY)
uv run db-init                                         # Create ops_agent_* tables
uv run db-reset-tables                                 # Drop/recreate ops_agent_*
uv run db-verify                                       # Verify tables exist
```
