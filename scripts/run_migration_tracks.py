#!/usr/bin/env python3
"""Run Alembic commands across configured migration tracks."""

from __future__ import annotations

import argparse
from dataclasses import dataclass
import os
from pathlib import Path
import re
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mugen.core.contract.migration_config import (
    MUGEN_CONFIG_FILE_ENV,
    load_mugen_config,
    resolve_mugen_config_path,
)
from mugen.core.utility.rdbms_schema import (
    DEFAULT_CORE_RDBMS_SCHEMA,
    resolve_core_rdbms_schema,
    validate_sql_identifier,
)

_TRACK_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


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


def _resolve_path(value: str, repo_root: Path) -> Path:
    """Resolve path relative to repository root when needed."""
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _validate_track_name(value: str) -> str:
    """Validate migration track names."""
    clean = value.strip()
    if not _TRACK_NAME_RE.fullmatch(clean):
        raise RuntimeError(f"Invalid migration track name: {value!r}")
    return clean


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
    track_name = _validate_track_name(name)
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


def _load_track_specs(cfg: dict, repo_root: Path) -> list[MigrationTrackSpec]:
    """Load configured track specs with defaults and structural validation."""
    tracks_cfg = cfg.get("rdbms", {}).get("migration_tracks", {})
    if tracks_cfg and not isinstance(tracks_cfg, dict):
        raise RuntimeError("rdbms.migration_tracks must be a table")

    core_schema = resolve_core_rdbms_schema(cfg, default=DEFAULT_CORE_RDBMS_SCHEMA)
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


def _select_tracks(
    track_specs: list[MigrationTrackSpec],
    selected_names: list[str],
    include_disabled: bool,
) -> list[MigrationTrackSpec]:
    """Select track specs to execute."""
    if selected_names:
        wanted = {_validate_track_name(item) for item in selected_names}
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


def _validate_execution_track(track_spec: MigrationTrackSpec) -> MigrationTrack:
    """Validate execution contract for one selected track."""
    if not track_spec.alembic_config.is_file():
        raise RuntimeError(
            f"Track '{track_spec.name}' Alembic config not found: {track_spec.alembic_config}",
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
    model_modules = _normalize_model_modules(
        track_spec.model_modules_raw,
        track_spec.name,
    )
    return MigrationTrack(
        name=track_spec.name,
        enabled=track_spec.enabled,
        alembic_config=track_spec.alembic_config,
        schema=schema,
        version_table=version_table,
        version_table_schema=version_table_schema,
        model_modules=model_modules,
    )


def _materialize_execution_tracks(
    track_specs: list[MigrationTrackSpec],
) -> list[MigrationTrack]:
    """Validate selected tracks and return execution-ready contracts."""
    return [_validate_execution_track(track_spec) for track_spec in track_specs]


def _build_track_env(track: MigrationTrack) -> dict[str, str]:
    """Build Alembic process environment for one track execution."""
    env = os.environ.copy()
    env["MUGEN_ALEMBIC_TRACK"] = track.name
    env["MUGEN_ALEMBIC_SCHEMA"] = track.schema
    env["MUGEN_ALEMBIC_VERSION_TABLE"] = track.version_table
    env["MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA"] = track.version_table_schema
    if track.model_modules:
        env["MUGEN_ALEMBIC_MODEL_MODULES"] = ",".join(track.model_modules)
    else:
        env.pop("MUGEN_ALEMBIC_MODEL_MODULES", None)
    return env


def _run_track(
    *,
    track: MigrationTrack,
    python_bin: str,
    alembic_args: list[str],
    repo_root: Path,
    dry_run: bool,
) -> int:
    """Run one Alembic command for one track."""
    cmd = [python_bin, "-m", "alembic", "-c", str(track.alembic_config), *alembic_args]
    print(
        f"==> track={track.name} schema={track.schema} "
        f"version={track.version_table_schema}.{track.version_table}",
        flush=True,
    )
    print("    " + " ".join(cmd), flush=True)
    if dry_run:
        return 0

    proc = subprocess.run(
        cmd,
        cwd=repo_root,
        env=_build_track_env(track),
        check=False,
    )
    return proc.returncode


def main() -> int:
    """Entry point."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "alembic_args",
        nargs=argparse.REMAINDER,
        help="Arguments forwarded to Alembic (for example: upgrade head).",
    )
    parser.add_argument(
        "--config-file",
        default=None,
        help=(
            "Path to mugen TOML config (default precedence: "
            "--config-file > MUGEN_CONFIG_FILE > mugen.toml)."
        ),
    )
    parser.add_argument(
        "--repo-root",
        default=".",
        help="Repository root directory (default: current directory).",
    )
    parser.add_argument(
        "--python",
        default=sys.executable,
        help="Python interpreter used to execute Alembic.",
    )
    parser.add_argument(
        "--track",
        action="append",
        default=[],
        help="Track name to run. Repeat for multiple tracks. Defaults to all enabled tracks.",
    )
    parser.add_argument(
        "--include-disabled",
        action="store_true",
        help="Allow explicitly selected disabled tracks to run.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print commands without executing Alembic.",
    )
    args = parser.parse_args()

    alembic_args = [item for item in args.alembic_args if item]
    if not alembic_args:
        parser.error("missing alembic args (example: upgrade head)")

    try:
        repo_root = Path(args.repo_root).resolve()
        config_file = resolve_mugen_config_path(
            args.config_file,
            repo_root=repo_root,
        )
        os.environ[MUGEN_CONFIG_FILE_ENV] = str(config_file)

        cfg = load_mugen_config(config_file)
        track_specs = _load_track_specs(cfg, repo_root)
        selected_track_specs = _select_tracks(
            track_specs,
            args.track,
            args.include_disabled,
        )
        selected_tracks = _materialize_execution_tracks(selected_track_specs)

        for track in selected_tracks:
            code = _run_track(
                track=track,
                python_bin=args.python,
                alembic_args=alembic_args,
                repo_root=repo_root,
                dry_run=args.dry_run,
            )
            if code != 0:
                return code
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
