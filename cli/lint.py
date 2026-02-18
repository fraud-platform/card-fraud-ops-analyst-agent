"""Code quality commands."""

import subprocess
import sys


def main() -> None:
    """Run ruff linter."""
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "ruff", "check", "app/", "tests/"],
            check=False,
        ).returncode
    )


def format_code() -> None:
    """Run ruff formatter."""
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "ruff", "format", "app/", "tests/"],
            check=False,
        ).returncode
    )
