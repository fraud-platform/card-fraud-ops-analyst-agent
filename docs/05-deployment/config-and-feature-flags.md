# Config and Feature Flags

All configuration is supplied via environment variables managed in Doppler. Never use `.env` files.

## Feature Flags

All flags use the `OPS_AGENT_` prefix and map to `FeatureFlagsConfig` in `app/core/config.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPS_AGENT_ENABLE_LLM_REASONING` | bool | `true` | Enable LLM reasoning layer. Requires valid provider settings. |
| `OPS_AGENT_ENABLE_RULE_DRAFT_EXPORT` | bool | `false` | Enable export of rule drafts to Rule Management API. Requires RM ingest endpoint. |
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | bool | `true` | Require human approval before any rule export. Must be `true` in all environments. |
| `OPS_AGENT_RULE_MANAGEMENT_BASE_URL` | string | — | Base URL for the Rule Management API (e.g., `http://localhost:8000`). |

### Environment Defaults

| Flag (without prefix) | Local | Test | Prod |
|-----------------------|-------|------|------|
| `ENABLE_LLM_REASONING` | `true` | `true` | `true` |
| `ENABLE_RULE_DRAFT_EXPORT` | `false` | `false` | `false` |
| `ENFORCE_HUMAN_APPROVAL` | `true` | `true` | `true` (enforced, raises on startup if `false`) |

### Human Approval Enforcement

`OPS_AGENT_ENFORCE_HUMAN_APPROVAL=false` is rejected at startup in production. The security validator raises a `RuntimeError` if this flag is `false` in a `PROD` environment. It must never be disabled in production.

## LLM Configuration

All LLM variables use the `LLM_` prefix and map to `LLMConfig` in `app/core/config.py`. The `LLM_PROVIDER` field uses the Ollama provider prefix format (`ollama/...` or `ollama_chat/...`) and is the single source for model selection.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `LLM_PROVIDER` | string | `ollama/gpt-oss:20b` | Ollama model string, e.g. `ollama/gpt-oss:20b` |
| `LLM_BASE_URL` | string | `https://ollama.com` | Ollama Cloud API base URL (localhost is rejected for planner/reasoning) |
| `LLM_API_KEY` | SecretStr | — | Ollama Cloud API key (falls back to `OLLAMA_API_KEY` when unset) |
| `LLM_TIMEOUT` | int | `30` | Request timeout in seconds |
| `LLM_MAX_RETRIES` | int | `1` | Maximum retry attempts on transient failures |
| `LLM_STAGE_TIMEOUT_SECONDS` | int | `20` | Hard timeout budget for the full reasoning stage |
| `LLM_CONSISTENCY_THRESHOLD` | float | `0.7` | Minimum agreement threshold for consistency checks |
| `LLM_PROMPT_GUARD_ENABLED` | bool | `true` | Enable prompt injection and PII guard |
| `LLM_MAX_PROMPT_TOKENS` | int | `4000` | Maximum tokens allowed in a single prompt |
| `LLM_MAX_COMPLETION_TOKENS` | int | `384` | Cap generated output tokens to keep latency bounded |

### Prompt Guard Security

When `LLM_PROMPT_GUARD_ENABLED=true` (default), the following protections are applied:

1. **Prompt Injection Detection**: Scans all prompt payloads for common injection patterns:
   - Instruction override attempts ("ignore previous instructions")
   - System role injection ("you are now...", "system:")
   - Jailbreak attempts
   - Safety override attempts

2. **Payload Size Limits**: Enforces maximum string length (50,000 chars) and JSON depth (10 levels)

3. **Validation on Block**: If injection patterns are detected, the LLM call is blocked and fallback reasoning is used

### LLM Output Validation

All LLM responses are validated and sanitized before use:

1. **Risk Level Normalization**: Invalid risk levels are normalized to `MEDIUM`
2. **Confidence Clamping**: Values outside 0.0-1.0 are clamped to valid range
3. **Content Sanitization**: Narrative and findings are scanned for injection patterns
4. **Sensitive Key Removal**: Any `system`, `instruction`, `password`, `secret`, or `token` keys are stripped
5. **Length Limits**: Narratives truncated to 2,000 chars, findings to 20 items, hypotheses to 10 items

### LLM Provider Example (Ollama Cloud)

Set these via Doppler, not directly in environment:
```bash
doppler secrets set LLM_PROVIDER=ollama/gpt-oss:20b
doppler secrets set LLM_BASE_URL=https://ollama.com
doppler secrets set LLM_API_KEY=<ollama-cloud-api-key>
```

## Core Application Config

These variables are always required and come from Doppler.

| Variable | Description |
|----------|-------------|
| `DATABASE_URL_APP` | PostgreSQL connection string for the app user (read + write to `ops_agent_*`, read from `fraud_gov`) |
| `DATABASE_URL_ADMIN` | PostgreSQL connection string for the admin user (DDL only, used by `db-init` scripts) |
| `AUTH0_DOMAIN` | Auth0 tenant domain (e.g., `dev-gix6qllz7yvs0rl8.us.auth0.com`) |
| `AUTH0_AUDIENCE` | Auth0 API audience (e.g., `https://fraud-ops-analyst-agent-api`) |
| `AUTH0_CLIENT_ID` | M2M client ID for service-to-service calls |
| `AUTH0_CLIENT_SECRET` | M2M client secret (SecretStr) |

## Vector Similarity Configuration

Vector search variables use the `VECTOR_` prefix and map to `VectorSearchConfig` in
`app/core/config.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `VECTOR_ENABLED` | bool | `true` | Enable vector embeddings + pgvector similarity path |
| `VECTOR_MODEL_NAME` | string | `mxbai-embed-large` | Embedding model name |
| `VECTOR_API_BASE` | string | `http://localhost:11434/api` | Embedding endpoint base (e.g. `http://localhost:11434/api`) |
| `VECTOR_API_KEY` | SecretStr | — | Optional API key (falls back to `OLLAMA_API_KEY`) |
| `VECTOR_DIMENSION` | int | `1024` | Expected embedding vector size |
| `VECTOR_SEARCH_LIMIT` | int | `20` | Maximum candidate matches to scan |
| `VECTOR_TIME_WINDOW_DAYS` | int | `90` | Search horizon for candidate transactions |
| `VECTOR_MIN_SIMILARITY` | float | `0.3` | Minimum similarity threshold for matches |
| `VECTOR_REQUEST_TIMEOUT_S` | float | `10.0` | Embedding API timeout |
| `VECTOR_RETRY_ATTEMPTS` | int | `3` | Retry count for vector DB search query |
| `VECTOR_RETRY_BACKOFF_SECONDS` | float | `0.25` | Base exponential backoff for retries |

### Recommended Demo Topology (Split Mode)

- Reasoning: cloud (`LLM_BASE_URL=https://ollama.com`)
- Embeddings: local (`VECTOR_API_BASE=http://localhost:11434/api`)

This configuration avoids cloud embedding availability issues while preserving cloud reasoning quality.

Container runtime behavior:
- When `VECTOR_API_BASE` is not set and the default `http://localhost:11434/api` is in effect,
  the service rewrites to `http://host.docker.internal:11434/api` inside Docker containers.
- If your Docker runtime does not support `host.docker.internal`, set `VECTOR_API_BASE`
  explicitly to a reachable embedding endpoint.

### Fail-Closed Behavior

When `VECTOR_ENABLED=true`, vector embedding/search failures are treated as dependency failures
(no silent attribute-only fallback). This is intentional so broken similarity infrastructure is
detected immediately in test and production paths.

## Scoring Configuration

Scoring thresholds use the `SCORING_` prefix and map to `ScoringConfig` in `app/core/config.py`.
These thresholds control fraud pattern detection sensitivity.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SCORING_VELOCITY_BURST_1H_THRESHOLD` | int | `10` | Transaction count threshold for 1-hour velocity burst |
| `SCORING_VELOCITY_BURST_6H_THRESHOLD` | int | `20` | Transaction count threshold for 6-hour velocity burst |
| `SCORING_DECLINE_RATIO_HIGH_THRESHOLD` | float | `0.5` | High decline ratio threshold (50%) |
| `SCORING_DECLINE_RATIO_MEDIUM_THRESHOLD` | float | `0.3` | Medium decline ratio threshold (30%) |
| `SCORING_CROSS_MERCHANT_HIGH_THRESHOLD` | int | `10` | High unique merchant threshold |
| `SCORING_CROSS_MERCHANT_MEDIUM_THRESHOLD` | int | `5` | Medium unique merchant threshold |
| `SCORING_AMOUNT_HIGH_THRESHOLD` | float | `1000` | High amount threshold ($) |
| `SCORING_AMOUNT_ELEVATED_THRESHOLD` | float | `500` | Elevated amount threshold ($) |
| `SCORING_AMOUNT_ZSCORE_OUTLIER_THRESHOLD` | float | `3.0` | Z-score for statistical outlier detection |
| `SCORING_AMOUNT_ZSCORE_WARNING_THRESHOLD` | float | `2.0` | Z-score for warning-level detection |
| `SCORING_SEVERITY_CRITICAL_THRESHOLD` | float | `0.7` | Severity score for CRITICAL |
| `SCORING_SEVERITY_HIGH_THRESHOLD` | float | `0.5` | Severity score for HIGH |
| `SCORING_SEVERITY_MEDIUM_THRESHOLD` | float | `0.3` | Severity score for MEDIUM |

### Round Number Detection

The `SCORING_AMOUNT_ROUND_NUMBERS` variable configures which round amounts trigger fraud alerts:

| Default Values |
|----------------|
| 100, 200, 300, 400, 500, 750, 1000, 1500, 2000, 5000, 10000 |

These are common fraud amounts - attackers often use round numbers.

### Unusual Hours

The `SCORING_TIME_UNUSUAL_HOURS` variable defines hours considered unusual for transactions:

| Default Values |
|----------------|
| 0, 1, 2, 3, 4, 5 (midnight to 5 AM) |

Transactions during these hours receive additional scrutiny, especially combined with high-risk merchant categories.

## Configuration Reload Behavior

Settings are loaded at application startup and cached using `@lru_cache` in `app/core/config.py`. This means:

- **Environment variable changes require server restart** - Changing Doppler secrets or environment variables will not take effect until the service is restarted.
- **No runtime configuration reload** - The `get_settings()` function returns cached values for the lifetime of the process.
- **Use `reload_settings()` for testing only** - A `reload_settings()` function exists to clear the cache, but this is only used in test scenarios, not in production code.

### Common Scenarios

| Action | Requires Restart? | Notes |
|--------|------------------|-------|
| Updating Doppler secrets | Yes | Server must restart to read new values |
| Changing feature flags | Yes | All feature flags are cached at startup |
| Rotating LLM API keys | Yes | `LLM_API_KEY` is loaded once at startup |
| Modifying database URLs | Yes | Connection pools use cached URLs |
| Adjusting log levels | Yes | `APP_LOG_LEVEL` is read-only after startup |

To apply configuration changes:
1. Update secrets in Doppler: `doppler secrets set LLM_API_KEY=<new-key>`
2. Restart the service: `kubectl rollout restart deployment/ops-analyst-agent` (Kubernetes) or restart the Docker container

## Metrics Token Management

The `/api/v1/metrics` endpoint requires authentication via `X-Metrics-Token` header. The token is configured via `METRICS_TOKEN` environment variable.

### Token Rotation Procedure

1. **Generate new token**: Create a new secure token (e.g., `openssl rand -hex 32`)
2. **Update Doppler**: `doppler secrets set METRICS_TOKEN=<new-token>`
3. **Update Prometheus scrape config**: Update the token in Prometheus configuration
4. **Restart service**: `kubectl rollout restart deployment/ops-analyst-agent`
5. **Verify**: Check Prometheus is successfully scraping metrics

### Security Recommendations

- Rotate metrics tokens every 90 days
- Use different tokens per environment (local, test, prod)
- Never commit tokens to version control
- Monitor for failed metric scrape attempts in logs

## JWKS Cache Configuration

The Auth0 JSON Web Key Set (JWKS) is cached to reduce network calls and improve authentication performance. Configuration is in `app/core/auth.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTH0_JWKS_CACHE_TTL` | int | `3600` | Cache time-to-live in seconds (1 hour) |

### Cache Behavior

- **In-memory caching** - JWKS is stored in module-level `_jwks_cache` variable
- **Async lock protection** - Concurrent requests use `asyncio.Lock()` to prevent cache stampede
- **Cache reuse** - If Auth0 is unavailable, stale cached JWKS is used for up to `TTL` seconds
- **Automatic refresh** - Cache is refreshed every hour or when cache expires

### Cache Invalidation

The cache cannot be invalidated at runtime. To force JWKS refresh:
1. Restart the service (clears all cached data)
2. Wait for `TTL` to expire (automatic background refresh)

### Monitoring

Watch for these log messages indicating cache behavior:
- `"Using stale JWKS cache"` - Auth0 unavailable, using expired cache
- `"Failed to fetch JWKS"` - Network or Auth0 errors (check connectivity)

## Request Size Limits

Multiple layers enforce size limits to prevent resource exhaustion and ensure system stability.

### API Query Limits

| Endpoint | Limit | Description |
|----------|-------|-------------|
| GET /worklist/recommendations | `page_size` ≤ 100 | Pagination limit enforced in route handler |
| GET /transactions/{id}/insights | None (single transaction) | Returns all insights for one transaction |
| POST /investigations/run | None | Validates request body size via FastAPI |
| GET /investigations/{investigation_id} | None | Single investigation run |

### Database Limits

| Resource | Limit | Configured In |
|----------|-------|---------------|
| DB connection pool | 10 connections per worker | `DATABASE_POOL_SIZE` |
| Max pool overflow | 10 additional connections | `DATABASE_MAX_OVERFLOW` |
| Max concurrent connections | 80 (4 workers × 20) | Calculated from workers × (pool_size + max_overflow) |
| Query timeout | 30 seconds | `DATABASE_POOL_TIMEOUT` |
| Statement timeout | Configured in PostgreSQL | Default: 60s in `fraud_gov` schema |

### LLM Prompt Limits

| Variable | Default | Purpose |
|----------|---------|---------|
| `LLM_MAX_PROMPT_TOKENS` | 4000 | Maximum tokens sent to LLM per request |
| `LLM_TIMEOUT` | 30 seconds | Maximum wait time for LLM response |
| `LLM_MAX_RETRIES` | 1 | Retry attempts on transient failures |
| `LLM_STAGE_TIMEOUT_SECONDS` | 20 seconds | Hard stage budget |
| `LLM_MAX_COMPLETION_TOKENS` | 384 | Output token cap for response latency control |

### Payload Size Guidelines

When sending large payloads:
- **Investigation runs**: Transaction context is truncated if it exceeds `LLM_MAX_PROMPT_TOKENS`
- **Rule drafts**: Limited by `LLM_MAX_PROMPT_TOKENS` - keep rule descriptions concise
- **Batch operations**: Not supported - use pagination for bulk reads
- **JSONB columns**: PostgreSQL JSONB has 1GB limit, but practical limit is ~100MB per row

### Memory Limits

| Resource | Limit | Notes |
|----------|-------|-------|
| Uvicorn worker memory | Monitored via OTEL | Alert if >2GB per worker |
| Request body size | 100MB | FastAPI default, enforced at reverse proxy |
| Response body size | None (streamed) | Large paginated responses are streamed |

### Monitoring

Track these metrics for size-related issues:
- `http_request_duration_seconds` - latency spikes may indicate oversized queries
- `db_connection_pool_usage` - pool exhaustion suggests too many concurrent requests
- `llm_request_tokens` - approaching limit indicates need for truncation or summarization

## Safe Defaults Summary

- LLM reasoning is on by default. Set provider/base/API key explicitly per environment.
- Vector similarity is on by default. Ensure `VECTOR_API_BASE` and embedding provider availability.
- Rule draft export is off. Enable only after Rule Management ingest endpoint is confirmed available.
- Human approval enforcement is on. This cannot be disabled in production.
- Prompt guard is on. Do not disable unless explicitly required and risk-accepted.
- Settings are cached. Restart service to apply Doppler secret changes.
