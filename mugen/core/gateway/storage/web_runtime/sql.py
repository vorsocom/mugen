"""SQL helpers for web runtime persistence adapters."""

from __future__ import annotations

from sqlalchemy import text as _sa_text
from sqlalchemy.sql.elements import TextClause


def text(sql: str) -> TextClause:
    """Build a SQLAlchemy text clause."""
    return _sa_text(sql)
