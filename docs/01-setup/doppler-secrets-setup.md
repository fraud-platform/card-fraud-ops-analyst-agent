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

- `AUTH0_USER_AUDIENCE` (shared portal human-user audience; platform-owned)
- `OPS_ANALYST_AUTH0_AUDIENCE` (Ops Agent M2M audience; service-owned)
- `AUTH0_AUDIENCE` (legacy fallback for standalone scripts and older configs)
- `AUTH0_CLIENT_ID` (service M2M)
- `AUTH0_CLIENT_SECRET` (service M2M)

#### LLM (Reasoning) configuration

- `LLM_PROVIDER` — model identifier in `provider/model` format (e.g. `openai/gpt-5-mini`)
- `LLM_BASE_URL` — API endpoint (e.g. `https://api.openai.com/v1`)
- `LLM_MAX_COMPLETION_TOKENS` — token budget per LLM call (recommended: `512`)
- `LLM_API_KEY` — required; OpenAI API key

#### Vector embeddings / similarity

- `VECTOR_ENABLED` (`true`/`false`)
- `VECTOR_API_BASE` — embeddings endpoint (e.g. `https://api.openai.com/v1`)
- `VECTOR_MODEL_NAME` — embedding model (e.g. `text-embedding-3-large`)
- `VECTOR_DIMENSION` — must match model output dimension (`1024` for text-embedding-3-large)
- `VECTOR_API_KEY` — optional; inherits `LLM_API_KEY` automatically for non-local endpoints

### Recommended local configuration

| Key | Value |
|-----|-------|
| `LLM_PROVIDER` | `openai/gpt-5-mini` |
| `LLM_BASE_URL` | `https://api.openai.com/v1` |
| `LLM_API_KEY` | *(your OpenAI key)* |
| `LLM_MAX_COMPLETION_TOKENS` | `512` |
| `VECTOR_ENABLED` | `true` |
| `VECTOR_API_BASE` | `https://api.openai.com/v1` |
| `VECTOR_MODEL_NAME` | `text-embedding-3-large` |
| `VECTOR_DIMENSION` | `1024` |

## Policy

- No hardcoded secrets in docs or repo files.
- Never use `.env` files; local runs should use Doppler.
- Any new secret requires documentation update in this file.

## Validation

- Confirm all required keys exist in local config.
- Confirm non-local configs (`test`, `prod`) are synchronized for shared keys.
