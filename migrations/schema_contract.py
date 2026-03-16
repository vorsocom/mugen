"""Shared core migration schema contract helpers for revision scripts."""

from __future__ import annotations

import os
import re

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MIGRATION_SCHEMA_ENV = "MUGEN_ALEMBIC_SCHEMA"
_CORE_SCHEMA_ENV = "MUGEN_ALEMBIC_CORE_SCHEMA"


def resolve_runtime_schema() -> str:
    """Resolve and validate required core runtime schema from Alembic env."""
    raw_value = os.getenv(_MIGRATION_SCHEMA_ENV, "")
    schema = raw_value.strip()
    if schema == "":
        raise RuntimeError(
            "Missing required migration schema: MUGEN_ALEMBIC_SCHEMA."
        )
    if not _IDENTIFIER_RE.fullmatch(schema):
        raise RuntimeError(
            f"Invalid migration schema in MUGEN_ALEMBIC_SCHEMA: {schema!r}"
        )
    return schema


def resolve_core_schema(*, default: str | None = None) -> str:
    """Resolve and validate the core runtime schema from Alembic env."""
    raw_value = os.getenv(_CORE_SCHEMA_ENV, "")
    schema = raw_value.strip()
    if schema == "" and isinstance(default, str):
        schema = default.strip()
    if schema == "":
        raise RuntimeError(
            "Missing required migration schema: MUGEN_ALEMBIC_CORE_SCHEMA."
        )
    if not _IDENTIFIER_RE.fullmatch(schema):
        raise RuntimeError(
            f"Invalid migration schema in MUGEN_ALEMBIC_CORE_SCHEMA: {schema!r}"
        )
    return schema


def rewrite_mugen_schema_sql(statement: str, *, schema: str) -> str:
    """Rewrite legacy literal `mugen.` schema qualifiers to runtime schema."""
    if not isinstance(statement, str):
        raise RuntimeError("Migration SQL statement must be a string.")
    return statement.replace("mugen.", f"{schema}.")
