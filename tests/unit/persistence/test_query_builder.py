"""Unit tests for persistence query builder helpers."""

from __future__ import annotations

from app.persistence.query_builder import build_optional_equals_where


def test_build_optional_equals_where_with_filters() -> None:
    where_clause, params = build_optional_equals_where(
        {"status": "IN_PROGRESS", "transaction_id": "txn-123"},
        param_aliases={"transaction_id": "txn_id"},
    )

    assert where_clause == "status = :status AND transaction_id = :txn_id"
    assert params == {"status": "IN_PROGRESS", "txn_id": "txn-123"}


def test_build_optional_equals_where_without_filters() -> None:
    where_clause, params = build_optional_equals_where(
        {"status": None, "transaction_id": None},
        param_aliases={"transaction_id": "txn_id"},
    )

    assert where_clause == "TRUE"
    assert params == {}


def test_build_optional_equals_where_skips_blank_strings() -> None:
    where_clause, params = build_optional_equals_where(
        {"status": "  ", "transaction_id": "txn-456"},
        param_aliases={"transaction_id": "txn_id"},
    )

    assert where_clause == "transaction_id = :txn_id"
    assert params == {"txn_id": "txn-456"}
