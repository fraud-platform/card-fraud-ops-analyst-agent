"""Base cursor for keyset pagination."""

import base64
import json
import uuid
from typing import Any


def row_to_dict(row: Any) -> dict[str, Any]:
    """Convert a SQLAlchemy row to a dict, casting UUID values to strings.

    asyncpg returns UUID columns as uuid.UUID objects. Pydantic schemas
    expect str for ID fields, so we convert here at the persistence boundary.
    """
    d = dict(row._mapping)
    return {k: str(v) if isinstance(v, uuid.UUID) else v for k, v in d.items()}


class CursorDecodeError(Exception):
    """Raised when cursor decoding fails."""

    pass


class BaseCursor:
    """Base class for keyset pagination cursors."""

    def __init__(self, values: dict[str, Any]):
        self.values = values

    def encode(self) -> str:
        """Encode cursor to base64 string."""
        json_str = json.dumps(self.values)
        return base64.urlsafe_b64encode(json_str.encode()).decode()

    @classmethod
    def decode(cls, cursor: str) -> BaseCursor:
        """Decode base64 string to cursor."""
        try:
            json_str = base64.urlsafe_b64decode(cursor.encode()).decode()
            values = json.loads(json_str)
            return cls(values)
        except (ValueError, json.JSONDecodeError) as e:
            raise CursorDecodeError(f"Invalid cursor: {cursor}") from e

    @classmethod
    def decode_optional(cls, cursor: str | None) -> BaseCursor | None:
        """Decode optional cursor string."""
        if cursor is None:
            return None
        try:
            return cls.decode(cursor)
        except CursorDecodeError:
            return None
