"""Root conftest for tests."""

import os

import pytest

if os.getenv("APP_ENV", "").strip().lower() == "prod":
    raise RuntimeError("Refusing to run tests with APP_ENV=prod")

# Force local test context so auth bypass remains test-only and deterministic.
os.environ["APP_ENV"] = "local"
os.environ["SECURITY_SKIP_JWT_VALIDATION"] = "true"
os.environ.setdefault("SERVER_PORT", "8003")
os.environ.setdefault("METRICS_TOKEN", "test-metrics-token")


def pytest_collection_modifyitems(items: list[pytest.Item]) -> None:
    """Auto-apply markers based on test directory structure.

    Maps directory → marker so `pytest -m unit` works without decorating every test.
    Directories: tests/unit → unit, tests/smoke → smoke,
                 tests/integration → integration, tests/e2e → e2e
    """
    dir_marker_map = {
        "unit": pytest.mark.unit,
        "smoke": pytest.mark.smoke,
        "integration": pytest.mark.integration,
        "e2e": pytest.mark.e2e,
    }
    for item in items:
        test_path = str(item.fspath)
        for dir_name, marker in dir_marker_map.items():
            if f"/{dir_name}/" in test_path or f"\\{dir_name}\\" in test_path:
                item.add_marker(marker)
                break


@pytest.fixture
def mock_session():
    """Mock database session for tests."""

    class MockSession:
        async def execute(self, *args, **kwargs):
            class MockResult:
                def fetchone(self):
                    return None

                def fetchall(self):
                    return []

            return MockResult()

        async def commit(self):
            pass

        async def rollback(self):
            pass

    return MockSession()
