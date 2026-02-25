"""Run repository quality gates for git hooks."""

from __future__ import annotations

import argparse
import shutil
import subprocess
from collections.abc import Sequence

CORE_GATE_COMMANDS: tuple[tuple[str, ...], ...] = (
    ("uv", "run", "ruff", "check", "app/", "tests/", "cli/", "scripts/"),
    ("uv", "run", "ruff", "format", "--check", "app/", "tests/", "cli/", "scripts/"),
    ("uv", "run", "pytest", "tests/unit", "tests/smoke", "-v"),
)

INTEGRATION_COMMANDS: tuple[tuple[str, ...], ...] = (
    (
        "doppler",
        "run",
        "--config",
        "local-test",
        "--",
        "uv",
        "run",
        "pytest",
        "tests/integration",
        "-v",
    ),
    ("doppler", "run", "--config", "local", "--", "uv", "run", "pytest", "tests/integration", "-v"),
)


def _run(command: Sequence[str]) -> int:
    print(f"\n$ {' '.join(command)}")
    completed = subprocess.run(command, check=False)
    if completed.returncode != 0:
        print(f"Command failed with exit code {completed.returncode}.")
    return completed.returncode


def run_core_gates() -> int:
    for command in CORE_GATE_COMMANDS:
        code = _run(command)
        if code != 0:
            return code
    return 0


def run_integration_gate() -> int:
    if shutil.which("doppler") is None:
        print("Doppler CLI not found. Install Doppler to run integration quality gate.")
        return 1

    first_code = _run(INTEGRATION_COMMANDS[0])
    if first_code == 0:
        return 0

    print("Retrying integration gate with Doppler config 'local' fallback.")
    return _run(INTEGRATION_COMMANDS[1])


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run quality gates for git hooks.")
    parser.add_argument(
        "--mode",
        choices=("core", "integration"),
        required=True,
        help="core: lint/format/unit/smoke, integration: doppler-backed integration tests",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    if args.mode == "core":
        return run_core_gates()
    if args.mode == "integration":
        return run_integration_gate()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
