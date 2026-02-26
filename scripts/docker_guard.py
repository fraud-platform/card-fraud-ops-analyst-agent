"""Guardrails to ensure local E2E traffic targets the Dockerized ops-agent service."""

from __future__ import annotations

import re
import subprocess
from datetime import UTC, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

LOCAL_HOSTS = {"localhost", "127.0.0.1"}
OPS_AGENT_NAME_HINTS = (
    "ops-agent",
    "ops_analyst",
    "ops-analyst",
    "card-fraud-ops",
)
TM_NAME_HINTS = (
    "transaction-management",
    "transaction_management",
    "transaction-mgmt",
    "card-fraud-transaction",
)
PROJECT_ROOT = Path(__file__).resolve().parent.parent
STALE_SKEW = timedelta(seconds=1)


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
            "Start services with: "
            "doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml "
            "--profile platform up -d --build transaction-management ops-analyst-agent"
        )

    ops_agent_containers = [name for name in published_on_8003 if _looks_like_ops_agent(name)]
    if ops_agent_containers:
        _assert_container_is_fresh(ops_agent_containers[0])
        return

    names = ", ".join(sorted(published_on_8003))
    raise RuntimeError(
        "Port 8003 is published by Docker, but not by an ops-agent container. "
        f"Found: {names}. Ensure the ops-agent app container is up."
    )


def assert_local_docker_transaction_management(base_url: str) -> None:
    """Validate local TM dependency is Dockerized transaction-management on localhost:8002."""
    parsed = urlparse(base_url)
    host = (parsed.hostname or "").lower()
    if host not in LOCAL_HOSTS:
        return

    if parsed.port != 8002:
        raise ValueError(
            f"Local TM dependency must target http://localhost:8002, got {base_url!r}. "
            "Set TM_BASE_URL correctly."
        )

    rows = _docker_ps_rows()
    published_on_8002 = [name for name, ports in rows if _publishes_local_8002(ports)]
    if not published_on_8002:
        raise RuntimeError(
            "No Docker container is publishing local port 8002 for Transaction Management. "
            "Start services with: "
            "doppler run -- docker compose -f docker-compose.yml -f docker-compose.apps.yml "
            "--profile platform up -d transaction-management"
        )

    tm_containers = [name for name in published_on_8002 if _looks_like_transaction_management(name)]
    if not tm_containers:
        names = ", ".join(sorted(published_on_8002))
        raise RuntimeError(
            "Port 8002 is published by Docker, but not by a transaction-management container. "
            f"Found: {names}."
        )

    health = _docker_container_health(tm_containers[0])
    if health not in {"healthy", "none"}:
        raise RuntimeError(
            "Transaction-management container is not healthy yet "
            f"(health={health!r}). Wait for readiness, then rerun."
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


def _assert_container_is_fresh(container_name: str) -> None:
    running_image_id, configured_image = _docker_inspect_container_image(container_name)
    configured_image_id = _docker_image_id(configured_image)

    if configured_image_id != running_image_id:
        raise RuntimeError(
            "Ops-agent container is stale: running image does not match configured image tag. "
            "Recreate it before E2E (docker compose ... up -d --build ops-analyst-agent)."
        )

    image_created_at = _docker_image_created_at(running_image_id)
    latest_source_mtime = _latest_runtime_source_mtime()
    if latest_source_mtime and latest_source_mtime > (image_created_at + STALE_SKEW):
        raise RuntimeError(
            "Ops-agent container is older than local source files. "
            "Rebuild/recreate container before E2E "
            "(docker compose ... up -d --build ops-analyst-agent)."
        )


def _docker_inspect_container_image(container_name: str) -> tuple[str, str]:
    result = _run_docker(
        ["docker", "inspect", container_name, "--format", "{{.Image}}\t{{.Config.Image}}"]
    )
    raw = (result.stdout or "").strip()
    parts = raw.split("\t", 1)
    if len(parts) != 2 or not parts[0] or not parts[1]:
        raise RuntimeError(
            f"Docker inspect returned unexpected payload for {container_name!r}: {raw!r}"
        )
    return parts[0].strip(), parts[1].strip()


def _docker_image_id(image_ref: str) -> str:
    result = _run_docker(["docker", "image", "inspect", image_ref, "--format", "{{.Id}}"])
    image_id = (result.stdout or "").strip()
    if not image_id:
        raise RuntimeError(f"Unable to resolve Docker image id for {image_ref!r}.")
    return image_id


def _docker_image_created_at(image_ref: str) -> datetime:
    result = _run_docker(["docker", "image", "inspect", image_ref, "--format", "{{.Created}}"])
    created_raw = (result.stdout or "").strip()
    if not created_raw:
        raise RuntimeError(f"Unable to resolve Docker image creation timestamp for {image_ref!r}.")
    return _parse_docker_datetime(created_raw)


def _latest_runtime_source_mtime() -> datetime | None:
    patterns = ("app/**/*.py", "Dockerfile", "pyproject.toml", "uv.lock")
    latest: datetime | None = None
    for pattern in patterns:
        for path in PROJECT_ROOT.glob(pattern):
            if not path.is_file():
                continue
            modified = datetime.fromtimestamp(path.stat().st_mtime, tz=UTC)
            if latest is None or modified > latest:
                latest = modified
    return latest


def _parse_docker_datetime(value: str) -> datetime:
    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"
    # Docker may emit nanosecond precision, but datetime only supports microseconds.
    raw = re.sub(r"\.(\d{6})\d+([+-]\d{2}:\d{2})$", r".\1\2", raw)
    return datetime.fromisoformat(raw).astimezone(UTC)


def _run_docker(args: list[str]) -> subprocess.CompletedProcess[str]:
    try:
        result = subprocess.run(
            args,
            check=False,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise RuntimeError("Docker CLI is not available in PATH.") from exc

    if result.returncode != 0:
        stderr = (result.stderr or "").strip()
        joined = " ".join(args)
        raise RuntimeError(f"Docker preflight failed for `{joined}`: {stderr or 'non-zero exit'}")
    return result


def _publishes_local_8003(ports: str) -> bool:
    # Docker ps port text normally includes `0.0.0.0:8003->8003/tcp` (and/or `[::]:8003->8003/tcp`).
    return "8003->8003/tcp" in ports


def _publishes_local_8002(ports: str) -> bool:
    # Docker ps port text normally includes `0.0.0.0:8002->8002/tcp` (and/or `[::]:8002->8002/tcp`).
    return "8002->8002/tcp" in ports


def _looks_like_ops_agent(container_name: str) -> bool:
    name = container_name.lower()
    return any(hint in name for hint in OPS_AGENT_NAME_HINTS)


def _looks_like_transaction_management(container_name: str) -> bool:
    name = container_name.lower()
    return any(hint in name for hint in TM_NAME_HINTS)


def _docker_container_health(container_name: str) -> str:
    result = _run_docker(
        [
            "docker",
            "inspect",
            container_name,
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        ]
    )
    return (result.stdout or "").strip().lower() or "none"
