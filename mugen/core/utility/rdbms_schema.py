"""Helpers for configurable RDBMS schema contracts and metadata translation."""

from __future__ import annotations

from dataclasses import dataclass
import re
from types import MappingProxyType

from sqlalchemy import MetaData
from sqlalchemy import Table

_CORE_SCHEMA_PATH = ("rdbms", "migration_tracks", "core", "schema")
_SQL_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TRACK_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")
_MISSING = object()

CORE_TRACK_NAME = "core"
CORE_SCHEMA_TOKEN = "mugen"
CONTEXT_ENGINE_TRACK_NAME = "context_engine"
AGENT_RUNTIME_TRACK_NAME = "agent_runtime"
CONTEXT_ENGINE_SCHEMA_TOKEN = "mugen_track_context_engine"
AGENT_RUNTIME_SCHEMA_TOKEN = "mugen_track_agent_runtime"
_TRACK_SCHEMA_TOKENS = MappingProxyType(
    {
        CORE_TRACK_NAME: CORE_SCHEMA_TOKEN,
        CONTEXT_ENGINE_TRACK_NAME: CONTEXT_ENGINE_SCHEMA_TOKEN,
        AGENT_RUNTIME_TRACK_NAME: AGENT_RUNTIME_SCHEMA_TOKEN,
    }
)


@dataclass(frozen=True)
class RDBMSSchemaContract:
    """Resolved runtime schema contract."""

    core_schema: str
    track_schemas: MappingProxyType
    schema_translate_map: MappingProxyType

    def schema_for_track(self, track_name: str) -> str:
        """Return the concrete schema for one migration/runtime track."""
        normalized_track = normalize_track_name(track_name)
        if normalized_track not in self.track_schemas:
            raise RuntimeError(f"Unknown migration track schema: {track_name!r}")
        return str(self.track_schemas[normalized_track])

    def token_for_track(self, track_name: str) -> str:
        """Return the schema token for one migration/runtime track."""
        return schema_token_for_track(track_name)

    def qualify(self, *, track_name: str, name: str) -> str:
        """Build a concrete schema-qualified SQL name for one track."""
        return qualify_sql_name(
            schema=self.schema_for_track(track_name),
            name=name,
        )


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


def normalize_track_name(value: object) -> str:
    """Validate migration track names."""
    if not isinstance(value, str):
        raise RuntimeError("Invalid migration track name: expected string.")
    clean = value.strip()
    if not _TRACK_NAME_RE.fullmatch(clean):
        raise RuntimeError(f"Invalid migration track name: {value!r}")
    return clean


def schema_token_for_track(track_name: str) -> str:
    """Return the stable logical schema token used by ORM metadata."""
    normalized_track = normalize_track_name(track_name)
    if normalized_track in _TRACK_SCHEMA_TOKENS:
        return str(_TRACK_SCHEMA_TOKENS[normalized_track])
    token_suffix = normalized_track.replace("-", "_")
    return f"mugen_track_{token_suffix}"


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


def _iter_plugin_track_entries(config: object) -> tuple[object, ...]:
    raw = _read_path(config, "rdbms", "migration_tracks", "plugins")
    if raw is _MISSING or raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError("Invalid configuration: rdbms.migration_tracks.plugins must be a list.")
    return tuple(raw)


def _track_entry_field(entry: object, field_name: str) -> object:
    if isinstance(entry, dict):
        return entry.get(field_name, _MISSING)
    if entry is None:
        return _MISSING
    return getattr(entry, field_name, _MISSING)


def resolve_plugin_track_schema(
    config: object,
    *,
    track_name: str,
    default: str | None = None,
) -> str:
    """Resolve one plugin-track schema with optional fallback."""
    normalized_track = normalize_track_name(track_name)
    for entry in _iter_plugin_track_entries(config):
        raw_name = _track_entry_field(entry, "name")
        if raw_name is _MISSING:
            continue
        if normalize_track_name(str(raw_name)) != normalized_track:
            continue
        raw_schema = _track_entry_field(entry, "schema")
        if raw_schema is _MISSING or raw_schema in (None, ""):
            break
        return validate_sql_identifier(
            raw_schema,
            label=f"schema for track '{normalized_track}'",
        )
    if default is None:
        raise RuntimeError(
            f"Invalid configuration: rdbms.migration_tracks.plugins track '{normalized_track}' is missing."
        )
    return validate_sql_identifier(
        default,
        label=f"default schema for track '{normalized_track}'",
    )


def resolve_rdbms_schema_contract(config: object) -> RDBMSSchemaContract:
    """Resolve concrete schemas and schema-translation contract for runtime use."""
    core_schema = resolve_core_rdbms_schema(config)
    track_schemas: dict[str, str] = {CORE_TRACK_NAME: core_schema}
    for entry in _iter_plugin_track_entries(config):
        raw_name = _track_entry_field(entry, "name")
        if raw_name is _MISSING:
            raise RuntimeError(
                "Invalid configuration: each migration track plugin entry requires name."
            )
        track_name = normalize_track_name(str(raw_name))
        raw_schema = _track_entry_field(entry, "schema")
        if raw_schema is _MISSING or raw_schema in (None, ""):
            raise RuntimeError(
                f"Invalid configuration: schema for track '{track_name}' is required."
            )
        track_schemas[track_name] = validate_sql_identifier(
            raw_schema,
            label=f"schema for track '{track_name}'",
        )

    # Built-in plugin runtime models continue to work when their track is not split
    # out yet by falling back to the core schema.
    track_schemas.setdefault(CONTEXT_ENGINE_TRACK_NAME, core_schema)
    track_schemas.setdefault(AGENT_RUNTIME_TRACK_NAME, core_schema)

    schema_translate_map = {
        schema_token_for_track(track_name): schema
        for track_name, schema in track_schemas.items()
    }
    return RDBMSSchemaContract(
        core_schema=core_schema,
        track_schemas=MappingProxyType(dict(track_schemas)),
        schema_translate_map=MappingProxyType(schema_translate_map),
    )


def clone_metadata_with_schema_map(
    metadata: MetaData,
    *,
    schema_map: dict[str, str] | MappingProxyType,
) -> MetaData:
    """Clone metadata with concrete schemas for Alembic autogenerate."""
    translated = MetaData(naming_convention=metadata.naming_convention)

    def _referred_schema(
        _table: Table,
        _source_schema: str | None,
        _constraint,
        referred_schema: str | None,
    ) -> str | None:
        if referred_schema is None:
            return None
        return str(schema_map.get(referred_schema, referred_schema))

    for table in metadata.tables.values():
        source_schema = table.schema
        target_schema = source_schema
        if source_schema is not None:
            target_schema = str(schema_map.get(source_schema, source_schema))
        table.to_metadata(
            translated,
            schema=target_schema,
            referred_schema_fn=_referred_schema,
        )
    return translated


def qualify_sql_name(*, schema: str, name: str) -> str:
    """Build a validated schema-qualified SQL name."""
    normalized_schema = validate_sql_identifier(schema, label="schema")
    normalized_name = validate_sql_identifier(name, label="name")
    return f"{normalized_schema}.{normalized_name}"
