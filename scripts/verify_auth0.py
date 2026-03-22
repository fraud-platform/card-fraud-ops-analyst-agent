"""Verify Auth0 configuration for Ops Analyst Agent.

Checks that the Auth0 API (Resource Server), M2M client, and
client grant are properly configured.

Required environment variables:
- AUTH0_MGMT_DOMAIN
- AUTH0_MGMT_CLIENT_ID
- AUTH0_MGMT_CLIENT_SECRET
- OPS_ANALYST_AUTH0_AUDIENCE

Legacy fallback:
- AUTH0_AUDIENCE (used when OPS_ANALYST_AUTH0_AUDIENCE is not set)
"""

from __future__ import annotations

import os
import sys

import httpx


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        print(f"FAIL: Missing required env var: {name}")
        sys.exit(1)
    return value


def _get_management_token(domain: str, client_id: str, client_secret: str) -> str:
    resp = httpx.post(
        f"https://{domain}/oauth/token",
        timeout=30.0,
        json={
            "grant_type": "client_credentials",
            "client_id": client_id,
            "client_secret": client_secret,
            "audience": f"https://{domain}/api/v2/",
        },
    )
    resp.raise_for_status()
    return resp.json()["access_token"]


def main() -> int:
    domain = _required_env("AUTH0_MGMT_DOMAIN")
    client_id = _required_env("AUTH0_MGMT_CLIENT_ID")
    client_secret = _required_env("AUTH0_MGMT_CLIENT_SECRET")
    audience = os.getenv("OPS_ANALYST_AUTH0_AUDIENCE") or os.getenv("AUTH0_AUDIENCE")
    if not audience:
        print("FAIL: Missing required env var: OPS_ANALYST_AUTH0_AUDIENCE")
        return 1

    unified_audience = "https://fraud-governance-api"

    print("=" * 60)
    print("AUTH0 VERIFICATION - Ops Analyst Agent")
    print("=" * 60)
    print(f"\nTenant: {domain}")
    print(f"Service Audience: {audience}")
    print(f"Unified Audience: {unified_audience}")

    errors = []

    # Get management token
    print("\n[1/4] Getting management token...")
    try:
        token = _get_management_token(domain, client_id, client_secret)
        print("  OK: Management token obtained")
    except Exception as e:
        print(f"  FAIL: Could not get management token: {e}")
        return 1

    client = httpx.Client(
        base_url=f"https://{domain}/api/v2/",
        headers={"Authorization": f"Bearer {token}"},
        timeout=30.0,
    )

    try:
        # Check Resource Server
        print("[2/4] Checking API (Resource Server)...")
        resp = client.get("resource-servers", params={"identifier": audience})
        resp.raise_for_status()
        servers = resp.json()
        found = None
        if isinstance(servers, list):
            for rs in servers:
                if rs.get("identifier") == audience:
                    found = rs
                    break

        if found:
            scopes = [s["value"] for s in found.get("scopes", [])]
            expected = [
                "ops_agent:read",
                "ops_agent:run",
                "ops_agent:ack",
                "ops_agent:draft",
                "ops_agent:admin",
            ]
            missing = [s for s in expected if s not in scopes]
            if missing:
                print(f"  WARN: Missing scopes: {missing}")
                errors.append(f"Missing scopes: {missing}")
            else:
                print(f"  OK: API found with {len(scopes)} scopes")
        else:
            print("  FAIL: API not found")
            errors.append("API not found")

        # Check M2M Client
        print("[3/4] Checking M2M application...")
        m2m_name = os.getenv("AUTH0_M2M_APP_NAME", "Fraud Ops Analyst Agent M2M")
        resp = client.get("clients", params={"page": 0, "per_page": 100})
        resp.raise_for_status()
        clients_list = resp.json()
        m2m_found = None
        if isinstance(clients_list, list):
            for c in clients_list:
                if c.get("name") == m2m_name:
                    m2m_found = c
                    break

        if m2m_found:
            print(f"  OK: M2M client found: {m2m_found.get('client_id')}")
        else:
            print(f"  WARN: M2M client '{m2m_name}' not found")
            errors.append(f"M2M client '{m2m_name}' not found")

        # Check Unified API (for human token validation from portal)
        print("[4/4] Checking unified API (human token audience)...")
        resp = client.get("resource-servers")
        resp.raise_for_status()
        all_servers = resp.json()
        unified_found = False
        if isinstance(all_servers, list):
            for rs in all_servers:
                if rs.get("identifier") == unified_audience:
                    unified_found = True
                    print(f"  OK: Unified API found: {rs.get('name')}")
                    break
        if not unified_found:
            print(f"  WARN: Unified API '{unified_audience}' not found")
            errors.append(
                f"Unified API '{unified_audience}' not found (needed for portal human tokens)"
            )

    finally:
        client.close()

    print("\n" + "=" * 60)
    if errors:
        print(f"VERIFICATION FAILED - {len(errors)} issue(s)")
        for e in errors:
            print(f"  - {e}")
    else:
        print("VERIFICATION PASSED")
    print("=" * 60)

    return 1 if errors else 0


if __name__ == "__main__":
    raise SystemExit(main())
