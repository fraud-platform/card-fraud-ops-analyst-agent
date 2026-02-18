"""CLI wrapper for Auth0 verification with Doppler."""

import sys

from cli._runner import run_doppler


def main():
    """Run Auth0 verification with Doppler secrets."""
    cmd = [sys.executable, "scripts/verify_auth0.py"]
    sys.exit(run_doppler("local", cmd))


if __name__ == "__main__":
    main()
