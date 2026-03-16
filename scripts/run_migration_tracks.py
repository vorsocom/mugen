#!/usr/bin/env python3
"""Run Alembic commands across configured migration tracks."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
import subprocess
import sys

_REPO_ROOT = Path(__file__).resolve().parents[1]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from mugen.core.contract.migration_config import (
    MUGEN_CONFIG_FILE_ENV,
    load_mugen_config,
    load_track_specs,
    materialize_execution_tracks,
    resolve_mugen_config_path,
    select_track_specs,
)
from mugen.core.utility.rdbms_schema import (
    resolve_core_rdbms_schema,
)


def _build_track_env(track: MigrationTrack) -> dict[str, str]:
    """Build Alembic process environment for one track execution."""
    env = os.environ.copy()
    env["MUGEN_ALEMBIC_TRACK"] = track.name
    env["MUGEN_ALEMBIC_SCHEMA"] = track.schema
    env["MUGEN_ALEMBIC_VERSION_TABLE"] = track.version_table
    env["MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA"] = track.version_table_schema
    env["MUGEN_ALEMBIC_CORE_SCHEMA"] = track.core_schema
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
        track_specs = load_track_specs(cfg, repo_root)
        selected_track_specs = select_track_specs(
            track_specs,
            selected_names=args.track,
            include_disabled=args.include_disabled,
        )
        selected_tracks = materialize_execution_tracks(
            selected_track_specs,
            core_schema=resolve_core_rdbms_schema(cfg),
        )

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
