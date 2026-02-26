"""Helpers for building safe, reusable SQL filter fragments."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any


def build_optional_equals_where(
    filters: Mapping[str, Any],
    *,
    param_aliases: Mapping[str, str] | None = None,
) -> tuple[str, dict[str, Any]]:
    """Build `column = :param` predicates for optional filter values.

    Notes:
    - Column names must be static/trusted (owned by application code), not user input.
    - `None` and empty-string values are skipped.
    """
    aliases = dict(param_aliases or {})
    conditions: list[str] = []
    params: dict[str, Any] = {}

    for column, value in filters.items():
        if value is None:
            continue
        if isinstance(value, str) and not value.strip():
            continue
        param_name = aliases.get(column, column)
        conditions.append(f"{column} = :{param_name}")
        params[param_name] = value

    where_clause = " AND ".join(conditions) if conditions else "TRUE"
    return where_clause, params
