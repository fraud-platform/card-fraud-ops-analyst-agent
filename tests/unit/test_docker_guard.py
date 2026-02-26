"""Unit tests for local Docker E2E guardrails."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import patch

import pytest

from scripts.docker_guard import (
    assert_local_docker_ops_agent,
    assert_local_docker_transaction_management,
)


def _cp(returncode: int = 0, stdout: str = "", stderr: str = "") -> SimpleNamespace:
    return SimpleNamespace(returncode=returncode, stdout=stdout, stderr=stderr)


def _run_side_effect(mapping: dict[tuple[str, ...], SimpleNamespace]):
    def _side_effect(args, check=False, capture_output=True, text=True):  # noqa: ANN001
        key = tuple(args)
        if key not in mapping:
            raise AssertionError(f"Unexpected docker command: {args}")
        return mapping[key]

    return _side_effect


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
    fake = _cp(stdout="card-fraud-postgres\t0.0.0.0:5432->5432/tcp\n")
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="No Docker container is publishing local port 8003"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_tm_no_container_publishing_8002_is_rejected() -> None:
    fake = _cp(stdout="card-fraud-postgres\t0.0.0.0:5432->5432/tcp\n")
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="local port 8002"):
            assert_local_docker_transaction_management("http://localhost:8002")


def test_tm_8002_published_by_non_tm_container_is_rejected() -> None:
    fake = _cp(stdout="random-service\t0.0.0.0:8002->8002/tcp\n")
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="not by a transaction-management container"):
            assert_local_docker_transaction_management("http://localhost:8002")


def test_tm_container_must_be_healthy() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-transaction-management\t0.0.0.0:8002->8002/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-transaction-management",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        ): _cp(stdout="starting\n"),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="not healthy yet"):
            assert_local_docker_transaction_management("http://localhost:8002")


def test_tm_container_on_8002_passes_when_healthy() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-transaction-management\t0.0.0.0:8002->8002/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-transaction-management",
            "--format",
            "{{if .State.Health}}{{.State.Health.Status}}{{else}}none{{end}}",
        ): _cp(stdout="healthy\n"),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        assert_local_docker_transaction_management("http://localhost:8002")


def test_8003_published_by_non_ops_container_is_rejected() -> None:
    fake = _cp(stdout="random-service\t0.0.0.0:8003->8003/tcp\n")
    with patch("scripts.docker_guard.subprocess.run", return_value=fake):
        with pytest.raises(RuntimeError, match="not by an ops-agent container"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_ops_agent_container_on_8003_passes() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch(
            "scripts.docker_guard._latest_runtime_source_mtime",
            return_value=datetime(2026, 2, 25, 14, 0, tzinfo=UTC),
        ),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")


def test_stale_container_image_mismatch_is_rejected() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:old\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:new\n"
        ),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="running image does not match configured image tag"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_stale_container_older_than_source_is_rejected() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch(
            "scripts.docker_guard._latest_runtime_source_mtime",
            return_value=datetime(2026, 2, 25, 16, 0, tzinfo=UTC),
        ),
    ):
        with pytest.raises(RuntimeError, match="older than local source files"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_latest_runtime_source_mtime_can_be_absent() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch("scripts.docker_guard._latest_runtime_source_mtime", return_value=None),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")


def test_parse_docker_preflight_failure_message_includes_command() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            returncode=1,
            stderr="daemon unavailable",
        ),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="Docker preflight failed"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_inspect_payload_shape_is_validated() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="bad-payload\n"),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="unexpected payload"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_image_id_lookup_requires_value() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(stdout="\n"),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="Unable to resolve Docker image id"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_image_created_lookup_requires_value() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(stdout="\n"),
    }
    with patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)):
        with pytest.raises(RuntimeError, match="creation timestamp"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_docker_cli_missing_while_running_command_is_reported() -> None:
    with patch("scripts.docker_guard.subprocess.run", side_effect=FileNotFoundError):
        with pytest.raises(RuntimeError, match="Docker CLI is not available"):
            assert_local_docker_ops_agent("http://localhost:8003")


def test_ops_agent_container_on_8003_passes_when_source_equal() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch(
            "scripts.docker_guard._latest_runtime_source_mtime",
            return_value=datetime(2026, 2, 25, 15, 0, tzinfo=UTC),
        ),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")


def test_ops_agent_container_on_8003_passes_when_no_source_mtime() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch("scripts.docker_guard._latest_runtime_source_mtime", return_value=None),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")


def test_ops_agent_container_on_8003_passes_with_small_skew() -> None:
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.000000000Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch(
            "scripts.docker_guard._latest_runtime_source_mtime",
            return_value=datetime(2026, 2, 25, 15, 0, 0, 500000, tzinfo=UTC),
        ),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")


def test_parse_docker_datetime_with_nanoseconds() -> None:
    # Regression guard for Docker timestamps with nanoseconds.
    mapping = {
        ("docker", "ps", "--format", "{{.Names}}\t{{.Ports}}"): _cp(
            stdout="card-fraud-ops-agent\t0.0.0.0:8003->8003/tcp\n"
        ),
        (
            "docker",
            "inspect",
            "card-fraud-ops-agent",
            "--format",
            "{{.Image}}\t{{.Config.Image}}",
        ): _cp(stdout="sha256:img1\tops-agent:dev\n"),
        ("docker", "image", "inspect", "ops-agent:dev", "--format", "{{.Id}}"): _cp(
            stdout="sha256:img1\n"
        ),
        ("docker", "image", "inspect", "sha256:img1", "--format", "{{.Created}}"): _cp(
            stdout="2026-02-25T15:00:00.123456789Z\n"
        ),
    }
    with (
        patch("scripts.docker_guard.subprocess.run", side_effect=_run_side_effect(mapping)),
        patch("scripts.docker_guard._latest_runtime_source_mtime", return_value=None),
    ):
        assert_local_docker_ops_agent("http://localhost:8003")
