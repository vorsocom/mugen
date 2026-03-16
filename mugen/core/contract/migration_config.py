"""Migration config and track-contract helpers shared by runner and Alembic env."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
import os
import tomllib

from mugen.core.utility.rdbms_schema import (
    normalize_track_name,
    resolve_core_rdbms_schema,
    validate_sql_identifier,
)

DEFAULT_MUGEN_CONFIG_FILE = "mugen.toml"
MUGEN_CONFIG_FILE_ENV = "MUGEN_CONFIG_FILE"

_REPO_ROOT = Path(__file__).resolve().parents[3]


@dataclass(frozen=True)
class MigrationTrackSpec:
    """Migration track configuration parsed from TOML."""

    name: str
    enabled: bool
    alembic_config: Path
    schema_raw: object
    version_table_raw: object
    version_table_schema_raw: object
    model_modules_raw: object = None


@dataclass(frozen=True)
class MigrationTrack:
    """Validated migration track execution contract."""

    name: str
    enabled: bool
    alembic_config: Path
    schema: str
    version_table: str
    version_table_schema: str
    model_modules: tuple[str, ...]
    core_schema: str


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


def _resolve_path(value: str, repo_root: Path) -> Path:
    """Resolve path relative to repository root when needed."""
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _normalize_model_modules(raw: object, track_name: str) -> tuple[str, ...]:
    """Normalize model module list for autogenerate workflows."""
    if raw is None:
        return ()
    if not isinstance(raw, list):
        raise RuntimeError(
            f"Track '{track_name}' has invalid model_modules; expected list[str].",
        )

    modules: list[str] = []
    for item in raw:
        if not isinstance(item, str):
            raise RuntimeError(
                f"Track '{track_name}' has non-string model_modules entry: {item!r}",
            )
        module_name = item.strip()
        if not module_name:
            continue
        modules.append(module_name)
    return tuple(modules)


def _build_track_spec(
    *,
    name: str,
    raw: dict,
    repo_root: Path,
    defaults: dict[str, str],
) -> MigrationTrackSpec:
    """Build one migration track spec from TOML config data."""
    track_name = normalize_track_name(name)
    enabled = bool(raw.get("enabled", True))

    alembic_config = _resolve_path(
        str(raw.get("alembic_config", defaults["alembic_config"])),
        repo_root,
    )

    schema_raw = raw.get("schema", defaults["schema"])
    version_table_raw = raw.get("version_table", defaults["version_table"])
    version_table_schema_raw = raw.get("version_table_schema", schema_raw)

    return MigrationTrackSpec(
        name=track_name,
        enabled=enabled,
        alembic_config=alembic_config,
        schema_raw=schema_raw,
        version_table_raw=version_table_raw,
        version_table_schema_raw=version_table_schema_raw,
        model_modules_raw=raw.get("model_modules"),
    )


def load_track_specs(cfg: dict, repo_root: Path) -> list[MigrationTrackSpec]:
    """Load configured track specs with defaults and structural validation."""
    tracks_cfg = cfg.get("rdbms", {}).get("migration_tracks", {})
    if tracks_cfg and not isinstance(tracks_cfg, dict):
        raise RuntimeError("rdbms.migration_tracks must be a table")

    core_schema = resolve_core_rdbms_schema(cfg)
    core_defaults = {
        "alembic_config": "alembic.ini",
        "schema": core_schema,
        "version_table": "alembic_version",
    }
    core_raw = tracks_cfg.get("core", {})
    if core_raw and not isinstance(core_raw, dict):
        raise RuntimeError("rdbms.migration_tracks.core must be a table")

    track_specs = [
        _build_track_spec(
            name="core",
            raw=core_raw if isinstance(core_raw, dict) else {},
            repo_root=repo_root,
            defaults=core_defaults,
        )
    ]

    plugin_raw = tracks_cfg.get("plugins", [])
    if plugin_raw and not isinstance(plugin_raw, list):
        raise RuntimeError("rdbms.migration_tracks.plugins must be an array of tables")

    for entry in plugin_raw:
        if not isinstance(entry, dict):
            raise RuntimeError("Each migration track plugin entry must be a table")

        name = entry.get("name")
        if not isinstance(name, str) or not name.strip():
            raise RuntimeError(
                "Each migration track plugin entry requires a non-empty 'name'",
            )

        default_schema = validate_sql_identifier(
            f"plugin_{name.strip().replace('-', '_')}",
            label=f"default schema for track '{name}'",
        )
        plugin_defaults = {
            "alembic_config": f"plugins/{name.strip()}/alembic.ini",
            "schema": default_schema,
            "version_table": "alembic_version",
        }
        track_specs.append(
            _build_track_spec(
                name=name,
                raw=entry,
                repo_root=repo_root,
                defaults=plugin_defaults,
            )
        )

    names = [track.name for track in track_specs]
    if len(names) != len(set(names)):
        raise RuntimeError(f"Duplicate migration track names detected: {names!r}")
    return track_specs


def select_track_specs(
    track_specs: list[MigrationTrackSpec],
    *,
    selected_names: list[str],
    include_disabled: bool,
) -> list[MigrationTrackSpec]:
    """Select track specs to execute."""
    if selected_names:
        wanted = {normalize_track_name(item) for item in selected_names}
        selected = [track for track in track_specs if track.name in wanted]
        missing = sorted(wanted.difference({track.name for track in track_specs}))
        if missing:
            raise RuntimeError(f"Unknown migration track(s): {', '.join(missing)}")

        if not include_disabled:
            disabled_selected = sorted(
                track.name for track in selected if not track.enabled
            )
            if disabled_selected:
                raise RuntimeError(
                    "Selected migration track(s) are disabled: "
                    f"{', '.join(disabled_selected)}. "
                    "Use --include-disabled to run disabled tracks."
                )

        effective = (
            selected
            if include_disabled
            else [track for track in selected if track.enabled]
        )
        if not effective:
            raise RuntimeError(
                "No effective migration tracks selected from --track options."
            )
        return effective

    selected = list(track_specs)
    effective = (
        selected if include_disabled else [track for track in selected if track.enabled]
    )
    if not effective:
        raise RuntimeError(
            "No migration tracks selected for execution; enable at least one track "
            "or use --include-disabled."
        )
    return effective


def materialize_execution_tracks(
    track_specs: list[MigrationTrackSpec],
    *,
    core_schema: str,
) -> list[MigrationTrack]:
    """Validate selected tracks and return execution-ready contracts."""
    tracks: list[MigrationTrack] = []
    for track_spec in track_specs:
        if not track_spec.alembic_config.is_file():
            raise RuntimeError(
                "Track "
                f"'{track_spec.name}' Alembic config not found: {track_spec.alembic_config}",
            )

        schema = validate_sql_identifier(
            str(track_spec.schema_raw),
            label=f"schema for track '{track_spec.name}'",
        )
        version_table = validate_sql_identifier(
            str(track_spec.version_table_raw),
            label=f"version_table for track '{track_spec.name}'",
        )
        version_table_schema = validate_sql_identifier(
            str(track_spec.version_table_schema_raw),
            label=f"version_table_schema for track '{track_spec.name}'",
        )
        tracks.append(
            MigrationTrack(
                name=track_spec.name,
                enabled=track_spec.enabled,
                alembic_config=track_spec.alembic_config,
                schema=schema,
                version_table=version_table,
                version_table_schema=version_table_schema,
                model_modules=_normalize_model_modules(
                    track_spec.model_modules_raw,
                    track_spec.name,
                ),
                core_schema=core_schema,
            )
        )
    return tracks


def _legacy_core_extension_error(key: str) -> RuntimeError:
    return RuntimeError(
        "Invalid configuration: "
        f"mugen.modules.core.{key} is no longer supported; "
        "use mugen.modules.extensions."
    )


def configured_extension_entries(config: dict) -> list[dict]:
    """Return unified extension entries and reject removed legacy contract keys."""
    modules_cfg = config.get("mugen", {}).get("modules", {})
    if isinstance(modules_cfg, dict) is not True:
        return []

    core_cfg = modules_cfg.get("core", {})
    if isinstance(core_cfg, dict):
        if "plugins" in core_cfg:
            raise _legacy_core_extension_error("plugins")
        if "extensions" in core_cfg:
            raise _legacy_core_extension_error("extensions")

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
