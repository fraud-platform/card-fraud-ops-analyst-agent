# Auth0 Setup Guide

## Objective

Define Auth0 scopes and roles for Ops Agent integration.

## API Audience

The shared portal audience is platform-owned:

- `AUTH0_USER_AUDIENCE` for human-user tokens minted by the portal SPA.

The ops-agent service keeps its own M2M audience:

- `OPS_ANALYST_AUTH0_AUDIENCE` for service-to-service tokens and bootstrap.

This repo accepts both audiences at runtime.

## Suggested Scopes

- `ops_agent:read` - read insights/recommendations.
- `ops_agent:run` - trigger on-demand investigations.
- `ops_agent:ack` - acknowledge/reject recommendations.
- `ops_agent:draft` - create/export draft rule packages.
- `ops_agent:admin` - operational controls and support functions.

## Role Mapping

- `FRAUD_ANALYST`: `ops_agent:read`, `ops_agent:run`, `ops_agent:ack`, `ops_agent:draft`
- `FRAUD_SUPERVISOR`: all analyst scopes plus escalation operations
- `PLATFORM_ADMIN`: all scopes including admin controls

## Security Constraints

- No privileged action through frontend-only checks; enforce in backend.
- Scope validation required on every mutating endpoint.
- Service-to-service tokens must use M2M client credentials.
