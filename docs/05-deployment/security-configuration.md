# Security Configuration

This document describes security configuration for the Card Fraud Ops Analyst Agent service, including CORS, JWT validation, request limits, and environment-specific settings.

## Overview

The service implements defense-in-depth security with the following layers:

1. **CORS controls** - Restricts cross-origin requests to approved sources
2. **JWT authentication** - Auth0-issued tokens validated against JWKS
3. **Authorization scopes** - Role-based access control via permission scopes
4. **Request validation** - Pydantic schemas with length and format checks
5. **Human approval enforcement** - Required for all rule draft exports in production
6. **Error sanitization** - Prevents information leakage via error messages
7. **Metrics endpoint token** - `/api/v1/metrics` requires `X-Metrics-Token`

All security configuration is managed through environment variables in Doppler. Never use `.env` files.

## Metrics Endpoint Token

Prometheus scraping endpoint `/api/v1/metrics` is protected by a shared secret header.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `METRICS_TOKEN` | string | — | Shared secret expected in `X-Metrics-Token` for `/api/v1/metrics` |

## CORS Configuration

Cross-Origin Resource Sharing (CORS) is configured via `SecurityConfig` in `app/core/config.py`.

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECURITY_CORS_ALLOWED_ORIGINS` | string | `http://localhost:3000,http://localhost:8000` | Comma-separated list of allowed origins |
| `SECURITY_CORS_ALLOW_CREDENTIALS` | bool | `true` | Allow cookies/auth headers in CORS requests |
| `SECURITY_CORS_ALLOW_METHODS` | list | `["GET","POST","PATCH","DELETE","PUT"]` | Allowed HTTP methods |
| `SECURITY_CORS_ALLOW_HEADERS` | list | `["Authorization","Content-Type","X-Request-ID"]` | Allowed request headers |

### Environment-Specific Origins

| Environment | Allowed Origins |
|-------------|-----------------|
| Local | `http://localhost:3000`, `http://localhost:8000` |
| Test | Test frontend and portal URLs (configure in Doppler) |
| Prod | Production frontend and portal URLs (configure in Doppler) |

### Configuration Example

```bash
# Allow multiple production origins
doppler secrets set SECURITY_CORS_ALLOWED_ORIGINS "https://fraud-portal.example.com,https://analyst-tools.example.com"
```

## JWT Validation

JSON Web Token (JWT) validation is implemented in `app/core/auth.py` using Auth0 RS256 signatures.

### Validation Flow

1. Extract `Authorization: Bearer <token>` header
2. Fetch JWKS from `https://{AUTH0_DOMAIN}/.well-known/jwks.json`
3. Match token `kid` header to JWKS key
4. Verify signature using RS256 algorithm
5. Validate audience (`AUTH0_AUDIENCE`) and issuer (`https://{AUTH0_DOMAIN}/`)
6. Extract permissions/scopes from token payload

### Environment Variables

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTH0_DOMAIN` | string | — | Auth0 tenant domain (e.g., `dev-gix6qllz7yvs0rl8.us.auth0.com`) |
| `AUTH0_AUDIENCE` | string | — | API audience identifier (e.g., `https://fraud-ops-analyst-agent-api`) |
| `AUTH0_ALGORITHMS` | string | `RS256` | Signature algorithms (comma-separated) |
| `AUTH0_JWKS_CACHE_TTL` | int | `3600` | JWKS cache duration in seconds (default: 1 hour) |

### JWKS Caching

JWKS are cached in memory to reduce Auth0 API calls:

- Cache TTL: 3600 seconds (1 hour) by default
- Stale cache fallback: If JWKS fetch fails, cached keys are used with a warning
- Locking: Async lock prevents thundering herd on cache refresh

### Local Development Bypass

For local development only, JWT validation can be bypassed:

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECURITY_SKIP_JWT_VALIDATION` | bool | `false` | Skip JWT validation (local environment only) |

**Security Validation:** If `SECURITY_SKIP_JWT_VALIDATION=true` in non-local environments, the service raises `ValueError` at startup and refuses to run.

When bypassed, the service returns a mock user with all permissions:
```python
AuthenticatedUser(
    user_id="local-dev-user",
    email="local-dev@example.com",
    permissions=["ops_agent:read", "ops_agent:run", "ops_agent:ack", "ops_agent:draft", "ops_agent:admin"]
)
```

**Usage:** Only enable this in local development. Never enable in test or production.

```bash
# Local development only
doppler secrets set SECURITY_SKIP_JWT_VALIDATION "true"
```

## Authorization Scopes

The service uses Auth0 custom scopes for fine-grained access control.

### Defined Scopes

| Scope | Permission | Endpoints |
|-------|------------|-----------|
| `ops_agent:read` | Read-only access | GET /insights, GET /recommendations, GET /investigations |
| `ops_agent:run` | Run investigations | POST /investigations/run |
| `ops_agent:ack` | Acknowledge recommendations | POST /worklist/recommendations/{id}/acknowledge |
| `ops_agent:draft` | Create rule drafts | POST /rule-drafts |
| `ops_agent:admin` | Administrative operations | Full access |

### Endpoint Protection

Endpoints are protected using dependency injection:

```python
from app.core.dependencies import RequireOpsRead, RequireOpsRun

@router.get("/transactions/{transaction_id}/insights")
async def get_insights(user: RequireOpsRead):  # Requires ops_agent:read
    ...
```

### Type Aliases

Pre-configured type aliases are available in `app/core/dependencies.py`:

```python
from app.core.dependencies import (
    RequireOpsRead,      # ops_agent:read
    RequireOpsRun,       # ops_agent:run
    RequireOpsAck,       # ops_agent:ack
    RequireOpsDraft,     # ops_agent:draft
    RequireOpsAdmin,     # ops_agent:admin
    CurrentUser,         # Authenticated user (no scope check)
)
```

## Human Approval Enforcement

The service enforces human approval for all rule draft exports to the Rule Management API.

### Environment Variable

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | bool | `true` | Require human approval before rule export |

### Production Enforcement

If `OPS_AGENT_ENFORCE_HUMAN_APPROVAL=false` in production (`APP_ENV=prod`), the service raises `RuntimeError` at startup:

```python
raise ValueError("Human approval enforcement must be enabled in production environment")
```

This is a hard security constraint that cannot be bypassed in production.

### Rule Draft Export Flow

1. Analyst creates rule draft via POST /rule-drafts
2. Draft is stored in `ops_agent_rule_drafts` table with `status=pending`
3. Analyst reviews draft in Rule Management UI
4. Analyst approves export via explicit action
5. Service validates `enforce_human_approval=true` before exporting

**Critical:** The service never auto-exports rule drafts. All exports require explicit human approval.

## Request Size Limits

The service enforces multiple layers of request size limits to prevent abuse.

### API Query Limits

| Endpoint | Parameter | Min | Max | Default |
|----------|-----------|-----|-----|---------|
| GET /worklist/recommendations | `limit` | 1 | 100 | 50 |

### Database Limits

| Resource | Limit | Description |
|----------|-------|-------------|
| Statement timeout | 30 seconds | PostgreSQL `statement_timeout` setting |
| Connection pool | 10 per worker | With 4 workers = 40 connections max |
| Pool overflow | 10 per worker | Total max = 80 connections |

### LLM Prompt Limits

| Resource | Limit | Environment Variable |
|----------|-------|---------------------|
| Max prompt tokens | 4000 | `LLM_MAX_PROMPT_TOKENS` |
| LLM request timeout | 30 seconds | `LLM_TIMEOUT` |

### Pipeline Timeout

The investigation pipeline has a 5-minute timeout:

```python
async with asyncio.timeout(300):  # 5 minutes maximum
    await self._run_pipeline(transaction_id, mode)
```

If the pipeline exceeds 5 minutes, it is cancelled and `AsyncioError` is returned.

## Security Headers

The service applies CORS headers via FastAPI middleware. Additional headers can be added via reverse proxy (nginx/envoy).

### CORS Headers Applied

```
Access-Control-Allow-Origin: <origin>
Access-Control-Allow-Credentials: true
Access-Control-Allow-Methods: GET, POST, PATCH, DELETE, PUT
Access-Control-Allow-Headers: Authorization, Content-Type, X-Request-ID
```

### Recommended Reverse Proxy Headers

Configure these at the ingress/load balancer level:

```
Strict-Transport-Security: max-age=31536000; includeSubDomains
X-Content-Type-Options: nosniff
X-Frame-Options: DENY
X-XSS-Protection: 1; mode=block
Content-Security-Policy: default-src 'self'
```

## Environment-Specific Settings

Security configuration varies by environment.

### Local Development

| Setting | Value |
|---------|-------|
| `APP_ENV` | `local` |
| `SECURITY_SKIP_JWT_VALIDATION` | `true` (opt-in) |
| `SECURITY_CORS_ALLOWED_ORIGINS` | `http://localhost:3000,http://localhost:8000` |
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | `true` |
| Debug endpoints | `/docs`, `/redoc`, `/openapi.json` enabled |

### Test Environment

| Setting | Value |
|---------|-------|
| `APP_ENV` | `test` |
| `SECURITY_SKIP_JWT_VALIDATION` | `false` (enforced) |
| `SECURITY_CORS_ALLOWED_ORIGINS` | Test frontend URLs |
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | `true` |
| Debug endpoints | Enabled |

### Production Environment

| Setting | Value |
|---------|-------|
| `APP_ENV` | `prod` |
| `SECURITY_SKIP_JWT_VALIDATION` | `false` (enforced at startup) |
| `SECURITY_CORS_ALLOWED_ORIGINS` | Production frontend URLs only |
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | `true` (enforced at startup) |
| Debug endpoints | Disabled (`/docs`, `/redoc`, `/openapi.json` return 404) |

## Configuration Reference

### SecurityConfig Variables

All security variables use the `SECURITY_` prefix and map to `SecurityConfig` in `app/core/config.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `SECURITY_CORS_ALLOWED_ORIGINS` | string | `http://localhost:3000,http://localhost:8000` | Comma-separated allowed origins |
| `SECURITY_CORS_ALLOW_CREDENTIALS` | bool | `true` | Allow credentials in CORS requests |
| `SECURITY_CORS_ALLOW_METHODS` | list | `["GET","POST","PATCH","DELETE","PUT"]` | Allowed HTTP methods |
| `SECURITY_CORS_ALLOW_HEADERS` | list | `["Authorization","Content-Type","X-Request-ID"]` | Allowed request headers |
| `SECURITY_SANITIZE_ERRORS` | bool | `true` | Sanitize error messages (hide internals) |
| `SECURITY_SKIP_JWT_VALIDATION` | bool | `false` | Bypass JWT validation (local only) |

### Auth0Config Variables

All Auth0 variables use the `AUTH0_` prefix and map to `Auth0Config` in `app/core/config.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `AUTH0_DOMAIN` | string | — | Auth0 tenant domain |
| `AUTH0_AUDIENCE` | string | — | API audience identifier |
| `AUTH0_CLIENT_ID` | string | — | M2M client ID for service-to-service calls |
| `AUTH0_CLIENT_SECRET` | SecretStr | — | M2M client secret |
| `AUTH0_ALGORITHMS` | string | `RS256` | Signature algorithms (comma-separated) |
| `AUTH0_JWKS_CACHE_TTL` | int | `3600` | JWKS cache duration in seconds |

### FeatureFlagsConfig Security Variables

Feature flags use the `OPS_AGENT_` prefix and map to `FeatureFlagsConfig` in `app/core/config.py`.

| Variable | Type | Default | Description |
|----------|------|---------|-------------|
| `OPS_AGENT_ENFORCE_HUMAN_APPROVAL` | bool | `true` | Require human approval for rule exports |

## Security Validation

The service validates security settings at startup via `Settings.validate_security_settings()`:

1. **JWT bypass check:** If `SECURITY_SKIP_JWT_VALIDATION=true` and `APP_ENV != local`, raise `ValueError`
2. **Human approval check:** If `APP_ENV=prod` and `OPS_AGENT_ENFORCE_HUMAN_APPROVAL=false`, raise `ValueError`

These validations prevent misconfiguration from reaching runtime.

## Additional Resources

- **Auth0 Setup:** See `docs/01-setup/auth0-setup-guide.md` for tenant configuration
- **API Security:** See `docs/03-api/ops-agent-api-contract-v1.md` for endpoint-specific security
- **Operations Security:** See `docs/06-operations/security-and-data-governance.md` for data handling policies
