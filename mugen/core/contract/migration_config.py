"""Migration config contract helpers shared by runner and Alembic env."""

from __future__ import annotations

from pathlib import Path
import os
import tomllib


DEFAULT_MUGEN_CONFIG_FILE = "mugen.toml"
MUGEN_CONFIG_FILE_ENV = "MUGEN_CONFIG_FILE"

_REPO_ROOT = Path(__file__).resolve().parents[3]


def _resolve_config_token(config_file: str | None) -> str:
    """Resolve config file token with CLI > env > default precedence."""
    if isinstance(config_file, str):
        cli_value = config_file.strip()
        if cli_value:
            return cli_value

    env_value = os.getenv(MUGEN_CONFIG_FILE_ENV, "").strip()
    if env_value:
        return env_value

    return DEFAULT_MUGEN_CONFIG_FILE


def resolve_mugen_config_path(
    config_file: str | None = None,
    *,
    repo_root: Path | None = None,
) -> Path:
    """Resolve absolute mugen config path using contract precedence."""
    root = repo_root if repo_root is not None else _REPO_ROOT
    token = _resolve_config_token(config_file)
    path = Path(token)
    if path.is_absolute() is not True:
        path = root / path
    return path.resolve()


def load_mugen_config(path: Path) -> dict:
    """Load mugen TOML config from a validated path."""
    try:
        with path.open("rb") as handle:
            data = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {path}") from exc
    except PermissionError as exc:
        raise RuntimeError(f"Config file is not readable: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise RuntimeError(f"Config file is not valid TOML: {path}") from exc

    if isinstance(data, dict) is not True:
        raise RuntimeError(f"Config file must parse to a TOML table: {path}")
    return data


def configured_core_extension_entries(config: dict) -> list[dict]:
    """Return core extension entries and reject removed legacy contract keys."""
    modules_cfg = config.get("mugen", {}).get("modules", {})
    if isinstance(modules_cfg, dict) is not True:
        return []

    core_cfg = modules_cfg.get("core", {})
    if isinstance(core_cfg, dict) is not True:
        return []

    if "plugins" in core_cfg:
        raise RuntimeError(
            "Invalid configuration: mugen.modules.core.plugins is no longer "
            "supported; use mugen.modules.core.extensions."
        )

    extension_entries = core_cfg.get("extensions", [])
    if extension_entries is None:
        return []
    if isinstance(extension_entries, list) is not True:
        raise RuntimeError(
            "Invalid configuration: mugen.modules.core.extensions must be an array."
        )

    normalized: list[dict] = []
    for index, entry in enumerate(extension_entries):
        if isinstance(entry, dict) is not True:
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.core.extensions[{index}] must be a table."
            )
        normalized.append(entry)
    return normalized


def configured_downstream_extension_entries(config: dict) -> list[dict]:
    """Return downstream extension entries with schema validation."""
    modules_cfg = config.get("mugen", {}).get("modules", {})
    if isinstance(modules_cfg, dict) is not True:
        return []

    extension_entries = modules_cfg.get("extensions", [])
    if extension_entries is None:
        return []
    if isinstance(extension_entries, list) is not True:
        raise RuntimeError(
            "Invalid configuration: mugen.modules.extensions must be an array."
        )

    normalized: list[dict] = []
    for index, entry in enumerate(extension_entries):
        if isinstance(entry, dict) is not True:
            raise RuntimeError(
                "Invalid configuration: "
                f"mugen.modules.extensions[{index}] must be a table."
            )
        normalized.append(entry)
    return normalized


def migration_schema_bootstrap_order(
    *,
    runtime_schema: str,
    version_table_schema: str,
) -> tuple[str, ...]:
    """Return deterministic schema creation order for migration bootstrapping."""
    if runtime_schema == version_table_schema:
        return (runtime_schema,)
    return (runtime_schema, version_table_schema)
