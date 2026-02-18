"""Runner utility for CLI commands."""

from __future__ import annotations

import subprocess

from cli._constants import DOPPLER_PROJECT


def run(cmd: list[str]) -> int:
    """Run a command and exit with its return code."""
    return subprocess.run(cmd, check=False).returncode


def run_doppler(config: str, cmd: list[str]) -> int:
    """Run a command with Doppler injecting environment variables.

    Args:
        config: Doppler config to use (e.g., 'local', 'test', 'prod')
        cmd: Command and arguments to run under Doppler

    Returns:
        The command's exit code
    """
    full_cmd = [
        "doppler",
        "run",
        "--project",
        DOPPLER_PROJECT,
        "--config",
        config,
        "--",
    ] + cmd
    return subprocess.run(full_cmd, check=False).returncode  # nosec
