"""Guardrails to ensure local E2E traffic targets the Dockerized ops-agent service."""

from __future__ import annotations

import subprocess
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
OPS_AGENT_NAME_HINTS = (
    "ops-agent",
    "ops_analyst",
    "ops-analyst",
    "card-fraud-ops",
)


def assert_local_docker_ops_agent(base_url: str) -> None:
    """Validate local E2E target is Dockerized ops-agent on localhost:8003.

    Rules:
    - Local host targets must use port 8003.
    - Port 8003 must be published by a running Docker container.
    - The publishing container name must look like the ops-agent service.
    """
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        return

    if parsed.port != 8003:
        raise ValueError(
            f"Local E2E must target http://localhost:8003, got {base_url!r}. "
            "Run ops-agent in Docker on port 8003."
        )

    rows = _docker_ps_rows()
    published_on_8003 = [name for name, ports in rows if _publishes_local_8003(ports)]

    if not published_on_8003:
        raise RuntimeError(
            "No Docker container is publishing local port 8003. "
            "Start platform apps with: "
            "doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml "
            "--profile apps up -d"
        )

    if any(_looks_like_ops_agent(name) for name in published_on_8003):
        return

    names = ", ".join(sorted(published_on_8003))
    raise RuntimeError(
        "Port 8003 is published by Docker, but not by an ops-agent container. "
        f"Found: {names}. Ensure the ops-agent app container is up."
    )


def _docker_ps_rows() -> list[tuple[str, str]]:
    try:
        result = subprocess.run(
            ["docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"],
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker CLI is not available in PATH.") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        raise RuntimeError(
            f"Docker preflight failed: {stderr or 'docker ps returned non-zero exit'}"
        )

    rows: list[tuple[str, str]] = []
    for line in (result.stdout or "").splitlines():
        if not line.strip():
            continue
        parts = line.split("\t", 1)
        if len(parts) != 2:
            continue
        name, ports = parts
        rows.append((name.strip(), ports.strip()))
    return rows


def _publishes_local_8003(ports: str) -> bool:
    # Docker ps port text normally includes `0.0.0.0:8003->8003/tcp` (and/or `[::]:8003->8003/tcp`).
    return "8003->8003/tcp" in ports


def _looks_like_ops_agent(container_name: str) -> bool:
    name = container_name.lower()
    return any(hint in name for hint in OPS_AGENT_NAME_HINTS)
