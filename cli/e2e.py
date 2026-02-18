"""CLI wrapper for e2e local test."""

from __future__ import annotations

import sys

from cli._runner import run_doppler


def main() -> None:
    """Run e2e local test with Doppler secrets."""
    code = run_doppler("local", [sys.executable, "scripts/e2e_local_test.py"])
    raise SystemExit(code)
