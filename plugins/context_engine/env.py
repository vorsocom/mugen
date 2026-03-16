"""Plugin-local Alembic environment for isolated migration tracks."""

from __future__ import annotations

from importlib import import_module
from logging.config import fileConfig
import os
from pathlib import Path
import re
from typing import Optional

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text
import tomlkit

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _load_mugen_config() -> dict:
    """Load mugen runtime TOML config."""
    config_file = Path(os.getenv("MUGEN_CONFIG_FILE", "mugen.toml")).resolve()
    try:
        with config_file.open("r", encoding="utf8") as handle:
            return tomlkit.loads(handle.read()).value
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {config_file}") from exc


def _identifier_from_env(name: str, default: str) -> str:
    """Read and validate SQL identifier from environment."""
    value = os.getenv(name, default).strip() or default
    if not _IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(f"Invalid identifier for {name}: {value!r}")
    return value


def _quote_identifier(name: str) -> str:
    """Quote an already-validated SQL identifier."""
    return f'"{name}"'


def _load_optional_target_metadata() -> Optional[MetaData]:
    """Load target metadata for autogenerate when explicitly configured."""
    module_name = os.getenv("MUGEN_ALEMBIC_METADATA_MODULE", "").strip()
    if not module_name:
        return None
    module = import_module(module_name)
    metadata = getattr(module, "metadata", None)
    if metadata is not None and not isinstance(metadata, MetaData):
        raise RuntimeError(
            "MUGEN_ALEMBIC_METADATA_MODULE must expose `metadata: MetaData`.",
        )
    return metadata


def _get_url(cfg: dict) -> str:
    """Resolve DB URL from mugen config."""
    return cfg["rdbms"]["alembic"]["url"]


_mugen_cfg = _load_mugen_config()
_runtime_schema = _identifier_from_env("MUGEN_ALEMBIC_SCHEMA", "plugin")
_version_table = _identifier_from_env("MUGEN_ALEMBIC_VERSION_TABLE", "alembic_version")
_version_table_schema = _identifier_from_env(
    "MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA",
    _runtime_schema,
)
_target_metadata = _load_optional_target_metadata()


def include_object(_obj, name, type_, _reflected, _compare_to):
    """Keep autogenerate away from this track's version table."""
    if type_ == "table" and name == _version_table:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in offline mode."""
    context.configure(
        url=_get_url(_mugen_cfg),
        target_metadata=_target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table=_version_table,
        version_table_schema=_version_table_schema,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in online mode."""
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url(_mugen_cfg)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema_sql = _quote_identifier(_runtime_schema)
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_sql}"))
        connection.execute(text(f"SET search_path TO {schema_sql}, public"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=_target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            version_table=_version_table,
            version_table_schema=_version_table_schema,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
