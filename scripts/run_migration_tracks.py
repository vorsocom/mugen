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
import tomllib

_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_TRACK_NAME_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_-]*$")


@dataclass(frozen=True)
class MigrationTrack:
    """Migration track execution contract."""

    name: str
    enabled: bool
    alembic_config: Path
    schema: str
    version_table: str
    version_table_schema: str
    model_modules: tuple[str, ...] = ()


def _load_toml(path: Path) -> dict:
    """Load TOML config document from path."""
    try:
        with path.open("rb") as handle:
            return tomllib.load(handle)
    except FileNotFoundError as exc:
        raise RuntimeError(f"Config file not found: {path}") from exc


def _resolve_path(value: str, repo_root: Path) -> Path:
    """Resolve path relative to repository root when needed."""
    path = Path(value)
    if not path.is_absolute():
        path = repo_root / path
    return path.resolve()


def _validate_identifier(value: str, label: str) -> str:
    """Validate SQL identifier-like values."""
    clean = value.strip()
    if not _IDENTIFIER_RE.fullmatch(clean):
        raise RuntimeError(f"Invalid {label}: {value!r}")
    return clean


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


def _build_track(
    *,
    name: str,
    raw: dict,
    repo_root: Path,
    defaults: dict[str, str],
) -> MigrationTrack:
    """Build one migration track from TOML config data."""
    track_name = _validate_track_name(name)
    enabled = bool(raw.get("enabled", True))

    alembic_config = _resolve_path(
        str(raw.get("alembic_config", defaults["alembic_config"])),
        repo_root,
    )
    if not alembic_config.is_file():
        raise RuntimeError(
            f"Track '{track_name}' Alembic config not found: {alembic_config}",
        )

    schema = _validate_identifier(
        str(raw.get("schema", defaults["schema"])),
        f"schema for track '{track_name}'",
    )
    version_table = _validate_identifier(
        str(raw.get("version_table", defaults["version_table"])),
        f"version_table for track '{track_name}'",
    )
    version_table_schema = _validate_identifier(
        str(raw.get("version_table_schema", schema)),
        f"version_table_schema for track '{track_name}'",
    )
    model_modules = _normalize_model_modules(raw.get("model_modules"), track_name)

    return MigrationTrack(
        name=track_name,
        enabled=enabled,
        alembic_config=alembic_config,
        schema=schema,
        version_table=version_table,
        version_table_schema=version_table_schema,
        model_modules=model_modules,
    )


def _load_tracks(cfg: dict, repo_root: Path) -> list[MigrationTrack]:
    """Load configured tracks with defaults and validation."""
    tracks_cfg = cfg.get("rdbms", {}).get("migration_tracks", {})
    if tracks_cfg and not isinstance(tracks_cfg, dict):
        raise RuntimeError("rdbms.migration_tracks must be a table")

    core_defaults = {
        "alembic_config": "alembic.ini",
        "schema": "mugen",
        "version_table": "alembic_version",
    }
    core_raw = tracks_cfg.get("core", {})
    if core_raw and not isinstance(core_raw, dict):
        raise RuntimeError("rdbms.migration_tracks.core must be a table")

    tracks = [
        _build_track(
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

        default_schema = _validate_identifier(
            f"plugin_{name.strip().replace('-', '_')}",
            f"default schema for track '{name}'",
        )
        plugin_defaults = {
            "alembic_config": f"plugins/{name.strip()}/alembic.ini",
            "schema": default_schema,
            "version_table": "alembic_version",
        }
        tracks.append(
            _build_track(
                name=name,
                raw=entry,
                repo_root=repo_root,
                defaults=plugin_defaults,
            )
        )

    names = [track.name for track in tracks]
    if len(names) != len(set(names)):
        raise RuntimeError(f"Duplicate migration track names detected: {names!r}")
    return tracks


def _select_tracks(
    tracks: list[MigrationTrack],
    selected_names: list[str],
    include_disabled: bool,
) -> list[MigrationTrack]:
    """Select enabled tracks or explicit track subset."""
    if selected_names:
        wanted = {_validate_track_name(item) for item in selected_names}
        selected = [track for track in tracks if track.name in wanted]
        missing = sorted(wanted.difference({track.name for track in tracks}))
        if missing:
            raise RuntimeError(f"Unknown migration track(s): {', '.join(missing)}")
    else:
        selected = list(tracks)

    if include_disabled:
        return selected
    return [track for track in selected if track.enabled]


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
        default="mugen.toml",
        help="Path to mugen TOML config (default: mugen.toml).",
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

    repo_root = Path(args.repo_root).resolve()
    config_file = _resolve_path(args.config_file, repo_root)

    cfg = _load_toml(config_file)
    tracks = _load_tracks(cfg, repo_root)
    selected_tracks = _select_tracks(tracks, args.track, args.include_disabled)

    if not selected_tracks:
        print("No migration tracks selected.")
        return 0

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

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
