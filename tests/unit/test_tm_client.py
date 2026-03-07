"""Unit tests for TMClient neighborhood query helpers."""

from __future__ import annotations

import pytest

from app.clients.tm_client import TMClient
from app.core.config import TMClientConfig


@pytest.mark.asyncio
async def test_tm_client_get_ip_neighborhood_builds_expected_params() -> None:
    client = TMClient(TMClientConfig(base_url="http://tm.local/api/v1"))

    captured: dict[str, object] = {}

    async def fake_paginated_list(*, params):
        captured["params"] = params
        return [{"transaction_id": "txn-1"}]

    client._paginated_list = fake_paginated_list  # type: ignore[method-assign]

    result = await client.get_ip_neighborhood("203.0.113.10", from_date="2026-02-28T00:00:00Z")

    assert result == [{"transaction_id": "txn-1"}]
    assert captured["params"] == {
        "ip_address": "203.0.113.10",
        "from_date": "2026-02-28T00:00:00Z",
        "page_size": 500,
    }


@pytest.mark.asyncio
async def test_tm_client_get_device_neighborhood_builds_expected_params() -> None:
    client = TMClient(TMClientConfig(base_url="http://tm.local/api/v1"))

    captured: dict[str, object] = {}

    async def fake_paginated_list(*, params):
        captured["params"] = params
        return [{"transaction_id": "txn-2"}]

    client._paginated_list = fake_paginated_list  # type: ignore[method-assign]

    result = await client.get_device_neighborhood("device-123", from_date="2026-02-28T00:00:00Z")

    assert result == [{"transaction_id": "txn-2"}]
    assert captured["params"] == {
        "device_id": "device-123",
        "from_date": "2026-02-28T00:00:00Z",
        "page_size": 500,
    }


@pytest.mark.asyncio
async def test_tm_client_get_fingerprint_neighborhood_builds_expected_params() -> None:
    client = TMClient(TMClientConfig(base_url="http://tm.local/api/v1"))

    captured: dict[str, object] = {}

    async def fake_paginated_list(*, params):
        captured["params"] = params
        return [{"transaction_id": "txn-3"}]

    client._paginated_list = fake_paginated_list  # type: ignore[method-assign]

    result = await client.get_device_fingerprint_neighborhood(
        "fp-hash-123", from_date="2026-02-28T00:00:00Z"
    )

    assert result == [{"transaction_id": "txn-3"}]
    assert captured["params"] == {
        "device_fingerprint_hash": "fp-hash-123",
        "from_date": "2026-02-28T00:00:00Z",
        "page_size": 500,
    }
