"""Unit tests for local Docker E2E guardrails."""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.docker_guard import assert_local_docker_ops_agent


def test_non_local_base_url_skips_docker_validation() -> None:
    with patch("scripts.docker_guard.subprocess.run") as run:
        assert_local_docker_ops_agent("https://ops-agent.internal.example.com")
        run.assert_not_called()


def test_local_non_8003_is_rejected() -> None:
    with pytest.raises(ValueError, match="localhost:8003"):
        assert_local_docker_ops_agent("http://localhost:8013")


def test_missing_docker_cli_is_rejected() -> None:
    with patch("scripts.docker_guard.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Docker CLI is not available"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_no_container_publishing_8003_is_rejected() -> None:
    fake = SimpleNamespace(
        returncode=0, stdout="card-fraud-postgres\t0.0.0.0:5432->5432/tcp\n", stderr=""
    )
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="No Docker container is publishing local port 8003"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_8003_published_by_non_ops_container_is_rejected() -> None:
    fake = SimpleNamespace(
        returncode=0,
        stdout="random-service\t0.0.0.0:8003->8003/tcp\n",
        stderr="",
    )
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="not by an ops-agent container"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_ops_agent_container_on_8003_passes() -> None:
    fake = SimpleNamespace(
        returncode=0,
        stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n",
        stderr="",
    )
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        assert_local_docker_ops_agent("http://localhost:8003")
