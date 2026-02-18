"""
Database setup commands with Doppler integration.

Usage:
    uv run db-init          # First-time setup (local)
    uv run db-init-test     # First-time setup (test)
    uv run db-reset-data    # Data reset
    uv run db-reset-tables  # Schema reset
    uv run db-verify        # Verify setup
"""

from __future__ import annotations

import sys
from pathlib import Path

from cli._runner import run_doppler

_SCRIPTS_DIR = Path(__file__).parent.parent / "scripts"
_SETUP_DB_SCRIPT = _SCRIPTS_DIR / "setup_database.py"


def _run_db_script(config: str, *extra_args: str) -> int:
    """Run database setup script with specified config."""
    cmd = [sys.executable, str(_SETUP_DB_SCRIPT), *extra_args]
    return run_doppler(config, cmd)


def db_init() -> None:
    """First-time database setup (local config)."""
    sys.exit(_run_db_script("local"))


def db_init_test() -> None:
    """First-time database setup (test config)."""
    sys.exit(_run_db_script("test"))


def db_init_prod() -> None:
    """First-time database setup (prod config)."""
    sys.exit(_run_db_script("prod"))


def db_reset_tables() -> None:
    """Drop and recreate ops_agent_* tables (local config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "reset_tables.py")]
    sys.exit(run_doppler("local", cmd))


def db_reset_tables_test() -> None:
    """Drop and recreate ops_agent_* tables (test config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "reset_tables.py")]
    sys.exit(run_doppler("test", cmd))


def db_reset_data() -> None:
    """Truncate data from ops_agent_* tables (local config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "reset_data.py")]
    sys.exit(run_doppler("local", cmd))


def db_reset_data_test() -> None:
    """Truncate data from ops_agent_* tables (test config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "reset_data.py")]
    sys.exit(run_doppler("test", cmd))


def db_verify() -> None:
    """Verify database setup (local config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "verify_database.py")]
    sys.exit(run_doppler("local", cmd))


def db_verify_test() -> None:
    """Verify database setup (test config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "verify_database.py")]
    sys.exit(run_doppler("test", cmd))


def db_verify_prod() -> None:
    """Verify database setup (prod config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "verify_database.py")]
    sys.exit(run_doppler("prod", cmd))


def db_load_test_data() -> None:
    """Seed integration/e2e test data into ops_agent_* and fraud_gov.transactions (local config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "load_test_data.py")]
    sys.exit(run_doppler("local", cmd))


def db_load_test_data_test() -> None:
    """Seed integration/e2e test data into ops_agent_* and fraud_gov.transactions (test config)."""
    cmd = [sys.executable, str(_SCRIPTS_DIR / "load_test_data.py")]
    sys.exit(run_doppler("test", cmd))
