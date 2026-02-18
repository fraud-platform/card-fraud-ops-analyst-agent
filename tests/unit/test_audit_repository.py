"""Unit tests for AuditRepository."""

from unittest.mock import AsyncMock, MagicMock

import pytest

from app.persistence.audit_repository import AuditRepository

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_row(**kwargs) -> MagicMock:
    """Create a mock row compatible with row_to_dict().

    row_to_dict() calls:
        d = dict(row._mapping)
        return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}

    So _mapping needs to behave like a dict that can be passed to dict().
    We use a real dict as _mapping so that dict(row._mapping) works correctly.
    """
    row = MagicMock()
    # Use a real dict as _mapping so dict(row._mapping) works
    row._mapping = kwargs
    return row


def _make_mock_session(fetchone_row=None, fetchall_rows=None):
    """Build an AsyncMock session whose execute returns a mock result."""
    mock_result = MagicMock()
    mock_result.fetchone.return_value = fetchone_row
    mock_result.fetchall.return_value = fetchall_rows or []

    mock_session = AsyncMock()
    mock_session.execute = AsyncMock(return_value=mock_result)
    return mock_session


# ---------------------------------------------------------------------------
# emit()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_emit_with_all_parameters_returns_dict():
    """emit() with all parameters inserts a row and returns a dict."""
    row = _make_mock_row(
        audit_id="aud-001",
        entity_type="recommendation",
        entity_id="rec-1",
        action="acknowledge",
        performed_by="analyst@example.com",
        old_value=None,
        new_value='{"status": "ACKNOWLEDGED"}',
        created_at="2026-02-15T10:00:00Z",
    )

    mock_session = _make_mock_session(fetchone_row=row)
    repo = AuditRepository(mock_session)

    result = await repo.emit(
        entity_type="recommendation",
        entity_id="rec-1",
        action="acknowledge",
        performed_by="analyst@example.com",
        old_value=None,
        new_value={"status": "ACKNOWLEDGED"},
    )

    assert result["audit_id"] == "aud-001"
    assert result["entity_type"] == "recommendation"
    assert result["entity_id"] == "rec-1"
    assert result["action"] == "acknowledge"
    assert result["performed_by"] == "analyst@example.com"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_emit_without_old_and_new_value_handles_none():
    """emit() with old_value=None and new_value=None serialises them as None."""
    row = _make_mock_row(
        audit_id="aud-002",
        entity_type="insight",
        entity_id="ins-1",
        action="create",
        performed_by="system",
        old_value=None,
        new_value=None,
        created_at="2026-02-15T11:00:00Z",
    )

    mock_session = _make_mock_session(fetchone_row=row)
    repo = AuditRepository(mock_session)

    result = await repo.emit(
        entity_type="insight",
        entity_id="ins-1",
        action="create",
        performed_by="system",
        old_value=None,
        new_value=None,
    )

    assert result["audit_id"] == "aud-002"
    assert result["old_value"] is None
    assert result["new_value"] is None

    # Verify the execute call passed None values (not json.dumps(None))
    call_args = mock_session.execute.call_args
    params = call_args[0][1]
    assert params["old_value"] is None
    assert params["new_value"] is None


@pytest.mark.asyncio
async def test_emit_with_old_and_new_value_serialises_to_json():
    """emit() serialises old_value and new_value dicts to JSON strings."""
    row = _make_mock_row(
        audit_id="aud-003",
        entity_type="recommendation",
        entity_id="rec-2",
        action="status_change",
        performed_by="user-1",
        old_value='{"status": "OPEN"}',
        new_value='{"status": "DISMISSED"}',
        created_at="2026-02-15T12:00:00Z",
    )

    mock_session = _make_mock_session(fetchone_row=row)
    repo = AuditRepository(mock_session)

    await repo.emit(
        entity_type="recommendation",
        entity_id="rec-2",
        action="status_change",
        performed_by="user-1",
        old_value={"status": "OPEN"},
        new_value={"status": "DISMISSED"},
    )

    call_args = mock_session.execute.call_args
    params = call_args[0][1]

    # Verify JSON serialisation happened
    import json

    assert json.loads(params["old_value"]) == {"status": "OPEN"}
    assert json.loads(params["new_value"]) == {"status": "DISMISSED"}


@pytest.mark.asyncio
async def test_emit_includes_audit_id_and_timestamp_in_query_params():
    """emit() generates a UUID audit_id and passes created_at to the query."""
    row = _make_mock_row(
        audit_id="aud-004",
        entity_type="run",
        entity_id="run-1",
        action="complete",
        performed_by="pipeline",
        old_value=None,
        new_value=None,
        created_at="2026-02-15T13:00:00Z",
    )

    mock_session = _make_mock_session(fetchone_row=row)
    repo = AuditRepository(mock_session)

    await repo.emit(
        entity_type="run",
        entity_id="run-1",
        action="complete",
        performed_by="pipeline",
    )

    call_args = mock_session.execute.call_args
    params = call_args[0][1]

    assert "audit_id" in params
    assert params["audit_id"]  # non-empty string UUID
    assert "created_at" in params
    assert params["entity_type"] == "run"
    assert params["entity_id"] == "run-1"
    assert params["action"] == "complete"
    assert params["performed_by"] == "pipeline"


# ---------------------------------------------------------------------------
# get_by_entity()
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_get_by_entity_returns_list_of_dicts():
    """get_by_entity() returns a list of dicts for all matching rows."""
    rows = [
        _make_mock_row(
            audit_id="aud-010",
            entity_type="recommendation",
            entity_id="rec-5",
            action="acknowledge",
            performed_by="analyst-1",
            old_value=None,
            new_value='{"status": "ACKNOWLEDGED"}',
            created_at="2026-02-15T10:05:00Z",
        ),
        _make_mock_row(
            audit_id="aud-011",
            entity_type="recommendation",
            entity_id="rec-5",
            action="create",
            performed_by="system",
            old_value=None,
            new_value='{"status": "OPEN"}',
            created_at="2026-02-15T10:00:00Z",
        ),
    ]

    mock_session = _make_mock_session(fetchall_rows=rows)
    repo = AuditRepository(mock_session)

    results = await repo.get_by_entity(
        entity_type="recommendation",
        entity_id="rec-5",
    )

    assert len(results) == 2
    assert all(isinstance(r, dict) for r in results)
    assert results[0]["audit_id"] == "aud-010"
    assert results[1]["audit_id"] == "aud-011"
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_by_entity_returns_empty_list_when_no_rows():
    """get_by_entity() returns an empty list when no audit entries exist."""
    mock_session = _make_mock_session(fetchall_rows=[])
    repo = AuditRepository(mock_session)

    results = await repo.get_by_entity(
        entity_type="recommendation",
        entity_id="rec-nonexistent",
    )

    assert results == []
    mock_session.execute.assert_called_once()


@pytest.mark.asyncio
async def test_get_by_entity_passes_correct_params():
    """get_by_entity() passes entity_type and entity_id to the query."""
    mock_session = _make_mock_session(fetchall_rows=[])
    repo = AuditRepository(mock_session)

    await repo.get_by_entity(
        entity_type="insight",
        entity_id="ins-99",
    )

    call_args = mock_session.execute.call_args
    params = call_args[0][1]

    assert params["entity_type"] == "insight"
    assert params["entity_id"] == "ins-99"


@pytest.mark.asyncio
async def test_get_by_entity_returns_dicts_with_all_expected_fields():
    """get_by_entity() returns dicts containing the core audit log fields."""
    row = _make_mock_row(
        audit_id="aud-020",
        entity_type="run",
        entity_id="run-42",
        action="pipeline_complete",
        performed_by="system",
        old_value=None,
        new_value='{"status": "SUCCESS"}',
        created_at="2026-02-15T14:00:00Z",
    )

    mock_session = _make_mock_session(fetchall_rows=[row])
    repo = AuditRepository(mock_session)

    results = await repo.get_by_entity(entity_type="run", entity_id="run-42")

    assert len(results) == 1
    result = results[0]
    assert "audit_id" in result
    assert "entity_type" in result
    assert "entity_id" in result
    assert "action" in result
    assert "performed_by" in result
    assert "created_at" in result


@pytest.mark.asyncio
async def test_emit_returns_row_to_dict_output():
    """emit() uses row_to_dict to convert the DB row, so UUID values become strings."""
    import uuid

    audit_uuid = uuid.UUID("12345678-1234-5678-1234-567812345678")

    row = _make_mock_row(
        audit_id=audit_uuid,  # UUID object — should be converted to str
        entity_type="recommendation",
        entity_id="rec-uuid-test",
        action="test",
        performed_by="tester",
        old_value=None,
        new_value=None,
        created_at="2026-02-15T10:00:00Z",
    )

    mock_session = _make_mock_session(fetchone_row=row)
    repo = AuditRepository(mock_session)

    result = await repo.emit(
        entity_type="recommendation",
        entity_id="rec-uuid-test",
        action="test",
        performed_by="tester",
    )

    # row_to_dict should have converted the UUID to a string
    assert isinstance(result["audit_id"], str)
    assert result["audit_id"] == "12345678-1234-5678-1234-567812345678"
