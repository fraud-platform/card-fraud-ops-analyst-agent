# Auth Model

## Identity Provider

Auth0 is the identity and authorization provider.

## Principal Types

- Human users (analysts, supervisors, admins).
- Service principals (TM, Rule Management, Ops Agent internals).

Human users authenticate through the platform-owned `AUTH0_USER_AUDIENCE`.
Ops-agent service-to-service traffic continues to use the service-specific M2M audience.

## API Scopes

- `ops_agent:read`
- `ops_agent:run`
- `ops_agent:ack`
- `ops_agent:draft`
- `ops_agent:admin`

## Role Mapping

- `FRAUD_ANALYST`: read/run/ack/draft
- `FRAUD_SUPERVISOR`: analyst + supervisory actions
- `PLATFORM_ADMIN`: full permissions

## Security Requirements

- Backend enforcement of every scope.
- No mutating action without explicit scope.
- Service-to-service uses dedicated M2M credentials.
- The shared credentials-exchange Action mirrors issued M2M access-token scopes into the top-level `permissions` claim so every backend authorizes against one claim.
