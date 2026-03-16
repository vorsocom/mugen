"""Plugin-local Alembic environment for isolated migration tracks."""

from __future__ import annotations

from importlib import import_module
from logging.config import fileConfig
import os
import re
from typing import Optional

from alembic import context
from sqlalchemy import MetaData
from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text

from mugen.core.contract.migration_config import (
    load_mugen_config,
    migration_schema_bootstrap_order,
    resolve_mugen_config_path,
)
from mugen.core.utility.rdbms_schema import (
    clone_metadata_with_schema_map,
    resolve_rdbms_schema_contract,
)

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

def _identifier_from_env(name: str, default: str) -> str:
    value = os.getenv(name, default).strip() or default
    if not _IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(f"Invalid identifier for {name}: {value!r}")
    return value


def _quote_identifier(name: str) -> str:
    return f'"{name}"'


def _load_optional_target_metadata() -> Optional[MetaData]:
    explicit_modules = [
        item.strip()
        for item in os.getenv("MUGEN_ALEMBIC_MODEL_MODULES", "").split(",")
        if item.strip()
    ]
    if explicit_modules:
        for module_name in explicit_modules:
            import_module(module_name)
        from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase  # pylint: disable=import-outside-toplevel

        return clone_metadata_with_schema_map(
            ModelBase.metadata,
            schema_map=_schema_contract.schema_translate_map,
        )

    module_name = os.getenv("MUGEN_ALEMBIC_METADATA_MODULE", "").strip()
    if not module_name:
        return None
    module = import_module(module_name)
    metadata = getattr(module, "metadata", None)
    if metadata is not None and not isinstance(metadata, MetaData):
        raise RuntimeError(
            "MUGEN_ALEMBIC_METADATA_MODULE must expose `metadata: MetaData`.",
        )
    return clone_metadata_with_schema_map(
        metadata,
        schema_map=_schema_contract.schema_translate_map,
    )


def _get_url(cfg: dict) -> str:
    return cfg["rdbms"]["alembic"]["url"]


_mugen_cfg = load_mugen_config(resolve_mugen_config_path())
_schema_contract = resolve_rdbms_schema_contract(_mugen_cfg)
_runtime_schema = _identifier_from_env("MUGEN_ALEMBIC_SCHEMA", "plugin")
_version_table = _identifier_from_env("MUGEN_ALEMBIC_VERSION_TABLE", "alembic_version")
_version_table_schema = _identifier_from_env(
    "MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA",
    _runtime_schema,
)
os.environ.setdefault("MUGEN_ALEMBIC_CORE_SCHEMA", _schema_contract.core_schema)
_target_metadata = _load_optional_target_metadata()
config.attributes["mugen_cfg"] = _mugen_cfg
config.attributes["rdbms_schema_contract"] = _schema_contract


def include_object(_obj, name, type_, _reflected, _compare_to):
    if type_ == "table" and name == _version_table:
        return False
    return True


def run_migrations_offline() -> None:
    context.configure(
        url=_get_url(_mugen_cfg),
        target_metadata=_target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table=_version_table,
        version_table_schema=_version_table_schema,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        **config.attributes,
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})
    configuration["sqlalchemy.url"] = _get_url(_mugen_cfg)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        for schema_name in migration_schema_bootstrap_order(
            runtime_schema=_runtime_schema,
            version_table_schema=_version_table_schema,
        ):
            bootstrap_schema_sql = _quote_identifier(schema_name)
            connection.execute(
                text(f"CREATE SCHEMA IF NOT EXISTS {bootstrap_schema_sql}")
            )
        runtime_schema_sql = _quote_identifier(_runtime_schema)
        connection.execute(text(f"SET search_path TO {runtime_schema_sql}, public"))
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
            **config.attributes,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
