"""Provides a minimal contract for a class that describes entity -> relational mapping."""

__all__ = ["IRelationalEntityMapping"]

from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class IRelationalEntityMapping:
    """A minimal contract for a class that describes entity -> relational mapping."""

    # Conceptual EDM type name.
    entity_type_name: str

    # Where to read/write it in the DB.
    table_name: str

    # How EDM properties map to DB columns.
    property_to_column: Mapping[str, str]  # {"Id": "id", "Name": "name", ...}

    # Optionally: which column(s) form the primary key at the DB level.
    primary_key: tuple[str, ...] | None = None
