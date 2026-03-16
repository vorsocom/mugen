"""Helpers for core RDBMS schema contract resolution and validation."""

from __future__ import annotations

import re

_CORE_SCHEMA_PATH = ("rdbms", "migration_tracks", "core", "schema")
_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_MISSING = object()


def _read_path(config: object, *path: str) -> object:
    current: object = config
    for key in path:
        if isinstance(current, dict):
            if key not in current:
                return _MISSING
            current = current[key]
            continue
        if current is None:
            return _MISSING
        if hasattr(current, key) is not True:
            return _MISSING
        current = getattr(current, key)
    return current


def validate_sql_identifier(value: object, *, label: str) -> str:
    """Validate and normalize SQL identifier-like values."""
    if not isinstance(value, str):
        raise RuntimeError(f"Invalid {label}: expected SQL identifier string.")
    clean = value.strip()
    if not _SQL_IDENTIFIER_RE.fullmatch(clean):
        raise RuntimeError(f"Invalid {label}: {value!r}")
    return clean


def resolve_core_rdbms_schema(
    config: object,
) -> str:
    """Resolve core runtime schema from migration-track contract."""
    raw_schema = _read_path(config, *_CORE_SCHEMA_PATH)
    if raw_schema is _MISSING or raw_schema is None or raw_schema == "":
        raise RuntimeError(
            "Invalid configuration: rdbms.migration_tracks.core.schema is required."
        )
    return validate_sql_identifier(
        raw_schema,
        label="rdbms.migration_tracks.core.schema",
    )


def qualify_sql_name(*, schema: str, name: str) -> str:
    """Build a validated schema-qualified SQL name."""
    normalized_schema = validate_sql_identifier(schema, label="schema")
    normalized_name = validate_sql_identifier(name, label="name")
    return f"{normalized_schema}.{normalized_name}"
