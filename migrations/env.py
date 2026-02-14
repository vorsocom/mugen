import importlib
from logging.config import fileConfig
import os
import sys
from typing import Optional

from sqlalchemy import engine_from_config
from sqlalchemy import pool
from sqlalchemy import text
from sqlalchemy import MetaData

import tomlkit

from alembic import context

# pylint: disable=no-member

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
    ext_cfg = []
    if "plugins" in cfg["mugen"]["modules"]["core"].keys():
        ext_cfg += cfg["mugen"]["modules"]["core"]["plugins"]

    if "extensions" in cfg["mugen"]["modules"].keys():
        ext_cfg += cfg["mugen"]["modules"]["extensions"]

    for ext in ext_cfg:
        ext_mod = ext.get("models")
        if ext_mod:
            importlib.import_module(ext["models"])


def _is_autogenerate_mode() -> bool:
    """Determine if Alembic is running `revision --autogenerate`."""
    cmd_opts = getattr(config, "cmd_opts", None)
    return bool(getattr(cmd_opts, "autogenerate", False))


def _is_truthy_env_var(name: str) -> bool:
    """Parse common truthy environment variable values."""
    value = os.getenv(name, "")
    return value.strip().lower() in {"1", "true", "yes", "on"}


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
    if type_ == "table" and name == "alembic_version":
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
        connection.execute(text("CREATE SCHEMA IF NOT EXISTS mugen"))
        connection.execute(text("SET search_path TO mugen, public"))
        connection.commit()

        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            compare_type=True,
            compare_server_default=True,
            include_schemas=True,
            version_table="alembic_version",
            version_table_schema="mugen",
            **config.attributes,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
