"""Test runner commands."""

import subprocess
import sys


def main() -> None:
    """Run unit tests."""
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/unit", "-v", "--tb=short"],
            check=False,
        ).returncode
    )


def test_smoke() -> None:
    """Run smoke tests."""
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/smoke", "-v", "--tb=short"],
            check=False,
        ).returncode
    )


def test_all() -> None:
    """Run all tests."""
    sys.exit(
        subprocess.run(
            [sys.executable, "-m", "pytest", "tests/", "-v", "--tb=short"],
            check=False,
        ).returncode
    )
