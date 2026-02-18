# Auth0 Setup Guide

## Objective

Define Auth0 scopes and roles for Ops Agent integration.

## API Audience

`OPS_AGENT_AUTH0_AUDIENCE` should represent the Ops Agent API.

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
