"""Auth0 bootstrap automation (idempotent) - Ops Analyst Agent.

This script provisions Auth0 objects for the Ops Analyst Agent API:
- Resource Server (API) with ops_agent:* permissions
- M2M Application for testing
- Client Grant with all scopes

NOTE: This script does NOT create roles. Roles are managed by
card-fraud-rule-management (the central hub). See auth-model.md.

Required environment variables:
- AUTH0_MGMT_DOMAIN              e.g. dev-xxxx.us.auth0.com
- AUTH0_MGMT_CLIENT_ID
- AUTH0_MGMT_CLIENT_SECRET
- AUTH0_AUDIENCE                 e.g. https://fraud-ops-analyst-agent-api

Optional environment variables:
- AUTH0_API_NAME                 default: Fraud Ops Analyst Agent API
- AUTH0_M2M_APP_NAME             default: Fraud Ops Analyst Agent M2M

Usage:
  uv run auth0-bootstrap --yes --verbose

Notes:
- This script avoids printing secrets.
- It is designed to be safe to re-run (idempotent).
- Run card-fraud-rule-management bootstrap FIRST to create shared roles.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import time
from dataclasses import dataclass

import httpx


def sync_secrets_to_doppler(
    secrets_dict: dict[str, str],
    *,
    project: str = "card-fraud-ops-analyst-agent",
    config: str = "local",
    verbose: bool = False,
) -> bool:
    """Sync secrets to Doppler using CLI."""
    if not secrets_dict:
        return True

    try:
        cmd = ["doppler", "secrets", "set", "--project", project, "--config", config]
        for key, value in secrets_dict.items():
            cmd.append(f"{key}={value}")

        result = subprocess.run(cmd, capture_output=True, encoding="utf-8", timeout=30)

        if result.returncode != 0:
            print(f"  Warning: Failed to sync to Doppler: {result.stderr}")
            return False

        if verbose:
            print(f"  Synced {len(secrets_dict)} secret(s) to Doppler ({project}/{config})")
        return True
    except subprocess.TimeoutExpired:
        print("  Warning: Doppler sync timed out")
        return False
    except FileNotFoundError:
        print("  Warning: Doppler CLI not found - skipping secret sync")
        return False
    except Exception as e:
        print(f"  Warning: Doppler sync error: {e}")
        return False


# Ops Analyst Agent API permissions (as defined in auth-model.md)
DEFAULT_SCOPES: list[dict[str, str]] = [
    {"value": "ops_agent:read", "description": "Read insights and recommendations"},
    {"value": "ops_agent:run", "description": "Trigger on-demand investigations"},
    {"value": "ops_agent:ack", "description": "Acknowledge or reject recommendations"},
    {"value": "ops_agent:draft", "description": "Create and export draft rule packages"},
    {"value": "ops_agent:admin", "description": "Operational controls and admin functions"},
]

# NOTE: Roles are NOT created by this project.
# Roles (PLATFORM_ADMIN, FRAUD_ANALYST, FRAUD_SUPERVISOR) are
# managed by card-fraud-rule-management. See auth-model.md.


def _required_env(name: str) -> str:
    value = os.getenv(name)
    if not value:
        raise SystemExit(f"Missing required env var: {name}")
    return value


@dataclass(frozen=True)
class Settings:
    mgmt_domain: str
    mgmt_client_id: str
    mgmt_client_secret: str
    audience: str
    api_name: str
    m2m_name: str


class Auth0Mgmt:
    def __init__(self, *, domain: str, token: str, timeout_s: float = 30.0, verbose: bool = False):
        self._domain = domain
        self._verbose = verbose
        self._client = httpx.Client(
            base_url=f"https://{domain}/api/v2/",
            headers={"Authorization": f"Bearer {token}"},
            timeout=timeout_s,
        )

    def close(self) -> None:
        self._client.close()

    def _request(
        self,
        method: str,
        path: str,
        *,
        params: dict | None = None,
        json: dict | list | None = None,
    ):
        max_attempts = 6
        base_sleep = 0.8
        last_exc: Exception | None = None

        for attempt in range(1, max_attempts + 1):
            try:
                resp = self._client.request(method, path, params=params, json=json)
            except (httpx.TimeoutException, httpx.TransportError) as exc:
                last_exc = exc
                if attempt == max_attempts:
                    raise
                time.sleep(base_sleep * attempt)
                continue

            if resp.status_code in (429, 500, 502, 503, 504):
                if attempt == max_attempts:
                    resp.raise_for_status()
                retry_after = resp.headers.get("Retry-After")
                if retry_after:
                    try:
                        sleep_s = float(retry_after)
                    except ValueError:
                        sleep_s = base_sleep * attempt
                else:
                    sleep_s = base_sleep * attempt
                time.sleep(sleep_s)
                continue

            resp.raise_for_status()
            if resp.status_code == 204:
                return None
            return resp.json()

        if last_exc:
            raise last_exc
        raise RuntimeError("Unexpected request retry state")

    def find_resource_server_by_identifier(self, identifier: str) -> dict | None:
        results = self._request("GET", "resource-servers", params={"identifier": identifier})
        if isinstance(results, list) and results:
            for rs in results:
                if rs.get("identifier") == identifier:
                    return rs
        return None

    def create_resource_server(
        self, *, name: str, identifier: str, scopes: list[dict[str, str]]
    ) -> dict:
        return self._request(
            "POST",
            "resource-servers",
            json={
                "name": name,
                "identifier": identifier,
                "scopes": scopes,
                "signing_alg": "RS256",
                "allow_offline_access": True,
                "token_lifetime": 7200,
                "token_lifetime_for_web": 7200,
                "enforce_policies": True,
                "token_dialect": "access_token_authz",
            },
        )

    def update_resource_server(
        self, *, resource_server_id: str, name: str, scopes: list[dict[str, str]]
    ) -> dict:
        return self._request(
            "PATCH",
            f"resource-servers/{resource_server_id}",
            json={
                "name": name,
                "scopes": scopes,
                "allow_offline_access": True,
                "enforce_policies": True,
                "token_dialect": "access_token_authz",
            },
        )

    def find_client_by_name(self, name: str) -> dict | None:
        page = 0
        while True:
            clients = self._request(
                "GET",
                "clients",
                params={"page": page, "per_page": 50, "fields": "client_id,name,app_type"},
            )
            if not isinstance(clients, list) or not clients:
                return None
            for client in clients:
                if client.get("name") == name:
                    return client
            if len(clients) < 50:
                return None
            page += 1

    def create_client(self, *, name: str, app_type: str, payload: dict) -> dict:
        body = {"name": name, "app_type": app_type, **payload}
        return self._request("POST", "clients", json=body)

    def update_client(self, *, client_id: str, payload: dict) -> dict:
        return self._request("PATCH", f"clients/{client_id}", json=payload)

    def list_client_grants(self, *, client_id: str) -> list[dict]:
        grants = self._request("GET", "client-grants", params={"client_id": client_id})
        return grants if isinstance(grants, list) else []

    def create_client_grant(self, *, client_id: str, audience: str, scope: list[str]) -> dict:
        return self._request(
            "POST",
            "client-grants",
            json={"client_id": client_id, "audience": audience, "scope": scope},
        )

    def update_client_grant(self, *, grant_id: str, scope: list[str]) -> dict:
        return self._request("PATCH", f"client-grants/{grant_id}", json={"scope": scope})


def _get_management_token(*, domain: str, client_id: str, client_secret: str) -> str:
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
    data = resp.json()
    token = data.get("access_token")
    if not token:
        raise SystemExit("Auth0 token response missing access_token")
    return token


def ensure_resource_server(
    mgmt: Auth0Mgmt,
    *,
    identifier: str,
    name: str,
    scopes: list[dict[str, str]],
    verbose: bool,
) -> dict:
    existing = mgmt.find_resource_server_by_identifier(identifier)
    if not existing:
        created = mgmt.create_resource_server(name=name, identifier=identifier, scopes=scopes)
        if verbose:
            print(f"Created resource server: {created.get('id')} ({identifier})")
        return created

    updated = mgmt.update_resource_server(
        resource_server_id=existing["id"], name=name, scopes=scopes
    )
    if verbose:
        print(f"Updated resource server: {updated.get('id')} ({identifier})")
    return updated


def ensure_m2m_client(mgmt: Auth0Mgmt, *, name: str, verbose: bool) -> dict:
    existing = mgmt.find_client_by_name(name)

    payload = {
        "app_type": "non_interactive",
        "grant_types": ["client_credentials"],
        "token_endpoint_auth_method": "client_secret_post",
        "oidc_conformant": True,
        "is_first_party": True,
    }

    if not existing:
        created = mgmt.create_client(name=name, app_type="non_interactive", payload=payload)
        if verbose:
            print(f"Created M2M client: {created.get('client_id')} ({name})")
        return created

    updated = mgmt.update_client(client_id=existing["client_id"], payload=payload)
    if verbose:
        print(f"Updated M2M client: {existing.get('client_id')} ({name})")
    return updated


def ensure_client_grant(
    mgmt: Auth0Mgmt, *, client_id: str, audience: str, scopes: list[str], verbose: bool
) -> dict:
    grants = mgmt.list_client_grants(client_id=client_id)
    existing = None
    for grant in grants:
        if grant.get("audience") == audience:
            existing = grant
            break

    if not existing:
        created = mgmt.create_client_grant(client_id=client_id, audience=audience, scope=scopes)
        if verbose:
            print(f"Created client grant: {created.get('id')} (client={client_id})")
        return created

    updated = mgmt.update_client_grant(grant_id=existing["id"], scope=scopes)
    if verbose:
        print(f"Updated client grant: {updated.get('id')} (client={client_id})")
    return updated


def load_settings() -> Settings:
    mgmt_domain = _required_env("AUTH0_MGMT_DOMAIN").strip()
    mgmt_client_id = _required_env("AUTH0_MGMT_CLIENT_ID").strip()
    mgmt_client_secret = _required_env("AUTH0_MGMT_CLIENT_SECRET").strip()
    audience = _required_env("AUTH0_AUDIENCE").strip()

    return Settings(
        mgmt_domain=mgmt_domain,
        mgmt_client_id=mgmt_client_id,
        mgmt_client_secret=mgmt_client_secret,
        audience=audience,
        api_name=os.getenv("AUTH0_API_NAME", "Fraud Ops Analyst Agent API"),
        m2m_name=os.getenv("AUTH0_M2M_APP_NAME", "Fraud Ops Analyst Agent M2M"),
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Bootstrap Auth0 objects for Ops Analyst Agent (idempotent)"
    )
    parser.add_argument("--yes", "-y", action="store_true", help="Run without prompting")
    parser.add_argument("--verbose", "-v", action="store_true", help="Print details")
    args = parser.parse_args()

    settings = load_settings()

    if not args.yes:
        print("=" * 60)
        print("AUTH0 BOOTSTRAP - Ops Analyst Agent")
        print("=" * 60)
        print(f"\nTenant: {settings.mgmt_domain}")
        print(f"Audience: {settings.audience}")
        print("\nThis will create/update:")
        print("  - API (Resource Server) with ops_agent:* permissions")
        print("  - M2M application for testing")
        print("\nNOTE: Roles are managed by card-fraud-rule-management.")
        print("      Run that bootstrap first if roles don't exist.")
        print("\nRe-run is safe (idempotent). Continue? [y/N] ", end="")
        answer = input().strip().lower()
        if answer not in ("y", "yes"):
            print("Aborted.")
            return 1

    print("\n[1/3] Getting management token...")
    token = _get_management_token(
        domain=settings.mgmt_domain,
        client_id=settings.mgmt_client_id,
        client_secret=settings.mgmt_client_secret,
    )

    mgmt = Auth0Mgmt(domain=settings.mgmt_domain, token=token, verbose=args.verbose)
    try:
        print("[2/3] Creating/updating API (Resource Server)...")
        ensure_resource_server(
            mgmt,
            identifier=settings.audience,
            name=settings.api_name,
            scopes=DEFAULT_SCOPES,
            verbose=args.verbose,
        )

        if args.verbose:
            print("  Skipping role creation (roles managed by rule-management)")

        print("[3/3] Creating/updating M2M application...")
        m2m_client = ensure_m2m_client(mgmt, name=settings.m2m_name, verbose=args.verbose)
        ensure_client_grant(
            mgmt,
            client_id=m2m_client["client_id"],
            audience=settings.audience,
            scopes=[s["value"] for s in DEFAULT_SCOPES],
            verbose=args.verbose,
        )

        m2m_secrets = {"AUTH0_CLIENT_ID": m2m_client["client_id"]}
        if "client_secret" in m2m_client:
            m2m_secrets["AUTH0_CLIENT_SECRET"] = m2m_client["client_secret"]
            if args.verbose:
                print("  Syncing M2M credentials to Doppler...")
            sync_secrets_to_doppler(m2m_secrets, verbose=args.verbose)
        elif args.verbose:
            print("  M2M client_secret not in response (existing client)")

    finally:
        mgmt.close()

    print("\n" + "=" * 60)
    print("AUTH0 BOOTSTRAP COMPLETED - Ops Analyst Agent")
    print("=" * 60)
    print("\nNext steps:")
    print("  1. Verify: uv run auth0-verify")
    print("  2. Ensure rule-management bootstrap was run for roles")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
