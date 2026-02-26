# Platform Docker Integration

## Deployment Target (v1)

First production-like target is the shared `card-fraud-platform` Docker stack.

## Compose Integration Requirements

- Add `ops-analyst-agent` service to `docker-compose.apps.yml`.
- Connect to `card-fraud-network`.
- Depend on healthy `transaction-management` and `postgres` services.
- Expose internal service port and health endpoint.

## Required Environment Variables

- App identity and env settings.
- DB connection strings for read and write roles.
- Auth0 audience/domain settings.
- LLM provider and fallback settings.
- Feature flags for continuous/on-demand modes.

## Health Endpoints

- Liveness: `/api/v1/health`
- Readiness: `/api/v1/health/ready`

## Startup Order

1. Shared infra healthy.
2. TM healthy and DB reachable.
3. Ops Agent starts and validates schema contracts.
4. Portal feature flags enabled for Ops Agent workspace.
