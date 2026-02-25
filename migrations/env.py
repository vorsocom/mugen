import importlib
from logging.config import fileConfig
import os
import re
import sys
from typing import Optional

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy import MetaData

import tomlkit

from alembic import context

# pylint: disable=no-member

# Accept Postgres identifier-style names for schema/version-table overrides.
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)


def _load_mugen_config(config_file: str) -> dict:
    """Load TOML configuration."""
    # Get application base path.
    rel = os.path.join(os.path.dirname(os.path.realpath(__file__)), "..")
    basedir = os.path.realpath(rel)
    # Attempt to read TOML config file.
    try:
        with open(os.path.join(basedir, config_file), "r", encoding="utf8") as f:
            cfg = tomlkit.loads(f.read()).value
            # Add base directory to configuration.
            cfg["basedir"] = basedir
            return cfg
    except FileNotFoundError:
        # Exit application if config file not found.
        sys.exit(1)


def _import_extension_models(cfg: dict) -> None:
    """Import extension declarative models to make alembic aware of them."""
    explicit_modules = _get_explicit_model_modules()
    if explicit_modules:
        for module_name in explicit_modules:
            importlib.import_module(module_name)
        return

    requested_track = _get_track_name()
    core_cfg = cfg.get("mugen", {}).get("modules", {}).get("core", {})
    root_cfg = cfg.get("mugen", {}).get("modules", {})

    # Core plugin entries default to the "core" migration track.
    for entry in core_cfg.get("plugins", []):
        _maybe_import_model(entry, default_track="core", requested_track=requested_track)

    # Extension entries default to the "downstream" migration track.
    for entry in root_cfg.get("extensions", []):
        _maybe_import_model(
            entry,
            default_track="downstream",
            requested_track=requested_track,
        )


def _maybe_import_model(entry: dict, default_track: str, requested_track: str) -> None:
    """Import an entry model module when track assignment matches."""
    if not isinstance(entry, dict):
        return

    module_name = entry.get("models")
    if not module_name:
        return

    entry_track = str(entry.get("migration_track", default_track)).strip() or default_track
    if entry_track != requested_track:
        return

    importlib.import_module(module_name)


def _is_autogenerate_mode() -> bool:
    """Determine if Alembic is running `revision --autogenerate`."""
    cmd_opts = getattr(config, "cmd_opts", None)
    return bool(getattr(cmd_opts, "autogenerate", False))


def _is_truthy_env_var(name: str) -> bool:
    """Parse common truthy environment variable values."""
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _get_track_name() -> str:
    """Return active migration track name for model-import filtering."""
    track = os.getenv("MUGEN_ALEMBIC_TRACK", "core").strip()
    return track or "core"


def _get_explicit_model_modules() -> list[str]:
    """
    Return explicit model modules to import for autogenerate.

    Format:
      MUGEN_ALEMBIC_MODEL_MODULES=module.one,module.two
    """
    raw = os.getenv("MUGEN_ALEMBIC_MODEL_MODULES", "")
    if not raw.strip():
        return []
    return [item.strip() for item in raw.split(",") if item.strip()]


def _get_identifier_from_env(name: str, default: str) -> str:
    """Return validated SQL identifier from env var fallback."""
    value = os.getenv(name, default).strip() or default
    if not _IDENTIFIER_RE.fullmatch(value):
        raise RuntimeError(f"Invalid identifier for {name}: {value!r}")
    return value


def _quote_identifier(name: str) -> str:
    """Quote an already-validated SQL identifier."""
    return f'"{name}"'


def _load_target_metadata(cfg: dict) -> Optional[MetaData]:
    """
    Load metadata only for autogenerate workflows.
    Runtime upgrade/downgrade does not require model imports and should avoid
    bootstrapping application-side package imports.

    Set `MUGEN_ALEMBIC_FORCE_MODEL_IMPORTS=1` to force metadata/model imports
    for non-autogenerate commands when needed.
    """
    if not (
        _is_autogenerate_mode()
        or _is_truthy_env_var("MUGEN_ALEMBIC_FORCE_MODEL_IMPORTS")
    ):
        return None

    from mugen.core.gateway.storage.rdbms.sqla.base import ModelBase  # pylint: disable=import-outside-toplevel

    _import_extension_models(cfg)
    return ModelBase.metadata


def get_url(cfg: dict) -> str:
    """Determine the database URL for migrations."""
    return cfg["rdbms"]["alembic"]["url"]


_mugen_cfg = _load_mugen_config("mugen.toml")

_RUNTIME_SCHEMA = _get_identifier_from_env("MUGEN_ALEMBIC_SCHEMA", "mugen")
_VERSION_TABLE = _get_identifier_from_env(
    "MUGEN_ALEMBIC_VERSION_TABLE",
    "alembic_version",
)
_VERSION_TABLE_SCHEMA = _get_identifier_from_env(
    "MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA",
    _RUNTIME_SCHEMA,
)

config.attributes["mugen_cfg"] = _mugen_cfg

# add your model's MetaData object here
# for 'autogenerate' support
# from myapp import mymodel
# target_metadata = mymodel.Base.metadata
target_metadata = _load_target_metadata(_mugen_cfg)


# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def include_object(_obj, name, type_, _reflected, _compare_to):
    """
    Exclude alembic_version so autogenerate never emits drop/create for it.
    """
    # Never let autogenerate “manage” Alembic’s internal version table
    if type_ == "table" and name == _VERSION_TABLE:
        return False
    return True


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = get_url(_mugen_cfg)
    context.configure(
        url=url,
        target_metadata=target_metadata,
        include_object=include_object,
        include_schemas=True,
        version_table=_VERSION_TABLE,
        version_table_schema=_VERSION_TABLE_SCHEMA,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
    # Start from alembic.ini config
    configuration = config.get_section(config.config_ini_section, {})
    # Override URL with our own
    configuration["sqlalchemy.url"] = get_url(_mugen_cfg)

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        schema_sql = _quote_identifier(_RUNTIME_SCHEMA)
        connection.execute(text(f"CREATE SCHEMA IF NOT EXISTS {schema_sql}"))
        connection.execute(text(f"SET search_path TO {schema_sql}, public"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            version_table=_VERSION_TABLE,
            version_table_schema=_VERSION_TABLE_SCHEMA,
            **config.attributes,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
