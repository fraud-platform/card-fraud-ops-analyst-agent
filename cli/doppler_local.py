"""
Doppler local commands for card-fraud-ops-analyst-agent.

Usage:
    uv run doppler-local        # Run dev server with Doppler secrets
    uv run doppler-local-test   # Run tests against local Docker DB
    uv run doppler-test         # Run tests against Neon test branch
    uv run doppler-prod         # Run tests against Neon prod branch
"""

from __future__ import annotations

import subprocess
import sys

from cli._constants import DOPPLER_PROJECT


def _run_with_doppler(
    config: str,
    script_name: str,
    extra_args: list[str] | None = None,
    extra_env: dict[str, str] | None = None,
) -> int:
    """Run a script with Doppler injecting environment variables."""
    import os
    from pathlib import Path

    script_path = Path(__file__).parent.parent / "scripts" / script_name

    cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        config,
        "--",
        sys.executable,
        str(script_path),
    ]
    if extra_args:
        cmd.extend(extra_args)

    env = os.environ.copy()
    env["DOPPLER_CONFIG"] = config
    if extra_env:
        env.update(extra_env)

    return subprocess.run(cmd, check=False, env=env).returncode


def main() -> None:
    """Run local dev server with Doppler secrets."""
    sys.exit(_run_with_doppler("local", "run_dev.py"))


def test_local() -> None:
    """Run tests against local Docker PostgreSQL with Doppler secrets."""
    sys.exit(
        _run_with_doppler(
            "local",
            "run_tests.py",
            extra_env={"SECURITY_SKIP_JWT_VALIDATION": "false"},
        )
    )


def test() -> None:
    """Run tests against Neon test branch with Doppler secrets."""
    sys.exit(_run_with_doppler("test", "run_tests.py"))


def test_prod() -> None:
    """Run tests against Neon prod branch with Doppler secrets."""
    sys.exit(_run_with_doppler("prod", "run_tests.py"))
