# Execution Plan: E2E Local Ollama Test + Security Audit + Docs Update + Git Push Prep

**Date:** 2026-02-14
**Status:** Awaiting approval

---

## Step 1: Fix LiteLLM Provider Bug

**File:** `app/llm/provider.py`

The `LiteLLMProvider.complete()` method never passes `api_base` or `api_key` to `litellm.acompletion()`. Without `api_base`, Ollama is unreachable.

**Change:** Add conditional `api_base` and `api_key` kwargs before the `acompletion()` call:

```python
call_kwargs = {}
if self.config.base_url:
    call_kwargs["api_base"] = self.config.base_url
if self.config.api_key.get_secret_value():
    call_kwargs["api_key"] = self.config.api_key.get_secret_value()

response = await litellm.acompletion(
    model=model,
    messages=messages,
    temperature=temperature,
    max_tokens=max_tokens,
    timeout=timeout,
    **call_kwargs,
    **kwargs,
)
```

---

## Step 2: Set Doppler Secrets for Local Ollama

```powershell
doppler secrets set \
  LLM_PROVIDER="ollama_chat/llama3.2" \
  LLM_BASE_URL="http://localhost:11434" \
  LLM_API_KEY="ollama" \
  LLM_TIMEOUT="120" \
  LLM_CONSISTENCY_THRESHOLD="0.3" \
  OPS_AGENT_ENABLE_LLM_REASONING="true" \
  --project card-fraud-ops-analyst-agent --config local
```

- `ollama_chat/llama3.2` — LiteLLM recommended format for Ollama chat models
- Timeout 120s — local 3B model can be slow on CPU
- Consistency threshold 0.3 — lower for local small-model testing

---

## Step 3: Tighten LiteLLM Version Pin

**File:** `pyproject.toml`

Change: `"litellm>=1.50.0"` -> `"litellm>=1.78.0,<2.0"`

Rationale: memory leak fixes in 1.78+, prevent silent major version breaks.

---

## Step 4: Write E2E Local Test Script

**New file:** `scripts/e2e_local_test.py`
**New CLI entry:** `e2e-local` in `pyproject.toml`

Script flow:
1. Verify Ollama reachable (`GET http://localhost:11434/api/tags`)
2. Verify DB connectivity, pick a real transaction ID
3. Run full investigation: `POST /api/v1/ops-agent/investigations/run`
4. Fetch detail: `GET /api/v1/ops-agent/investigations/{run_id}`
5. Fetch insights: `GET /api/v1/ops-agent/transactions/{txn_id}/insights`
6. List worklist: `GET /api/v1/ops-agent/worklist/recommendations`
7. Acknowledge a recommendation
8. Validate LLM reasoning present (`model_mode`, narrative, findings)
9. Print rich output with timing per stage

Runs against a **running server** (user starts with `uv run doppler-local`).

---

## Step 5: Update Docs to Reflect Implementation Reality

| File | Action | Description |
|------|--------|-------------|
| `README.md` | Rewrite | Remove "design phase", add Quick Start, Stack, Status |
| `DEVELOPER_GUIDE.md` | Rewrite | Actual dev workflow, Quality Gates, CLI Commands, LLM Config |
| `docs/01-setup/local-setup.md` | Rewrite | Real setup steps + Ollama setup |
| `docs/05-deployment/config-and-feature-flags.md` | Rewrite | Actual flag names + LLM config vars |
| `docs/03-api/portal-integration.md` | Update | Reflect portal UI completion |
| `docs/04-testing/testing-strategy.md` | Update | Add e2e + LLM testing sections |

---

## Step 6: Security Audit

Run security-auditor agent to check:
- No secrets in tracked files
- OWASP Top 10 (injection, auth bypass, XSS)
- JWT validation correctness
- CORS configuration
- Sensitive data in logs
- `.gitignore` coverage

---

## Step 7: Quality Gates

```bash
uv run ruff check app/ tests/ cli/ scripts/           # Lint (0 errors)
uv run ruff format --check app/ tests/ cli/ scripts/   # Format (clean)
uv run pytest tests/unit -v
uv run pytest tests/smoke -v
```

---

## Step 8: E2E Test with Ollama

Manual verification steps:
1. Ensure Ollama running with llama3.2 pulled
2. Seed DB: `uv run db-load-test-data`
3. Start server: `uv run doppler-local` (terminal 1)
4. Run e2e: `doppler run --project card-fraud-ops-analyst-agent --config local -- python scripts/e2e_local_test.py` (terminal 2)

---

## Step 9: Git Prep

- `git status` — verify no secrets
- Stage all files
- Commit with descriptive message

---

## Files to Create/Modify

| File | Action |
|------|--------|
| `app/llm/provider.py` | Fix: pass api_base + api_key to litellm |
| `pyproject.toml` | Edit: tighten litellm pin, add e2e-local CLI |
| `scripts/e2e_local_test.py` | New: comprehensive e2e test script |
| `README.md` | Rewrite |
| `DEVELOPER_GUIDE.md` | Rewrite |
| `docs/01-setup/local-setup.md` | Rewrite |
| `docs/05-deployment/config-and-feature-flags.md` | Rewrite |
| `docs/03-api/portal-integration.md` | Update |
| `docs/04-testing/testing-strategy.md` | Update |

---

## Verification Checklist

- [ ] Quality gates pass (lint/format clean, required suites green)
- [ ] `provider.py` passes `api_base` to litellm
- [ ] Doppler has LLM secrets set
- [ ] E2E script runs against real DB + Ollama
- [ ] Response contains `model_mode: "hybrid"` with LLM narrative
- [ ] Security audit clean
- [ ] All docs updated
- [ ] `.gitignore` covers .env, secrets, caches
- [ ] `git status` shows no sensitive files
