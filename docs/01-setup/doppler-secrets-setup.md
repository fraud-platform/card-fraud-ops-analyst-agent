# Doppler Secrets Setup

## Objective

Define required secrets for the Ops Agent service and map ownership.

## Secret Ownership Model

- Shared infra secrets remain in `card-fraud-platform` Doppler project.
- Service-specific secrets belong to `card-fraud-ops-analyst-agent` Doppler project.

## Required Secrets

### Platform-level inherited

- `POSTGRES_ADMIN_PASSWORD`
- `FRAUD_GOV_APP_PASSWORD`
- `AUTH0_DOMAIN`

Object storage (`S3_*`) secrets are not used by the current Ops Agent runtime and should not
be provisioned unless artifact export is implemented in a future phase.

### Ops Agent-specific

- `AUTH0_AUDIENCE` (Ops Agent API audience)
- `AUTH0_CLIENT_ID` (service M2M)
- `AUTH0_CLIENT_SECRET` (service M2M)

#### LLM (Reasoning) configuration

- `LLM_PROVIDER` (e.g. `ollama/gpt-oss:20b`)
- `LLM_BASE_URL` (`https://ollama.com` for planner/reasoning)
- `LLM_API_KEY` (Ollama Cloud API key)

If you prefer a single key name for Ollama Cloud, you can set:
- `OLLAMA_API_KEY` (the service will use this as a fallback for `LLM_API_KEY` and `VECTOR_API_KEY`)

#### Vector embeddings / similarity

- `VECTOR_ENABLED` (`true`/`false`)
- `VECTOR_API_BASE` (local: `http://localhost:11434/api`, cloud: `https://ollama.com/api`)
- `VECTOR_MODEL_NAME` (e.g. `mxbai-embed-large`)
- `VECTOR_API_KEY` (optional; falls back to `OLLAMA_API_KEY`)

### Recommended local split mode

For analyst demos, use cloud reasoning and local embeddings:

- Reasoning (cloud): `LLM_BASE_URL=https://ollama.com`
- Embeddings (local): `VECTOR_API_BASE=http://localhost:11434/api`

This avoids cloud embedding-model availability gaps while keeping high-quality cloud reasoning.

## Policy

- No hardcoded secrets in docs or repo files.
- Never use `.env` files; local runs should use Doppler.
- Any new secret requires documentation update in this file.

## Validation

- Confirm all required keys exist in local config.
- Confirm non-local configs (`test`, `prod`) are synchronized for shared keys.
