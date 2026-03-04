#!/usr/bin/env python3
"""Assess Alembic migrations for correctness and consistency."""

from __future__ import annotations

import argparse
import ast
import getpass
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile
import tomllib
from typing import Iterable


class CheckerError(RuntimeError):
    """Raised when a validation step cannot complete."""


_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def _validate_identifier(value: object, *, label: str) -> str:
    if not isinstance(value, str):
        raise CheckerError(f"{label} must be a SQL identifier string.")
    clean = value.strip()
    if not _IDENTIFIER_RE.fullmatch(clean):
        raise CheckerError(f"Invalid {label}: {value!r}")
    return clean


def _quote_identifier(identifier: str) -> str:
    return f'"{identifier}"'


def _build_env(repo_root: Path) -> dict[str, str]:
    """Build process env with repo root prepended to PYTHONPATH."""
    env = os.environ.copy()
    current = env.get("PYTHONPATH")
    env["PYTHONPATH"] = f"{repo_root}{os.pathsep}{current}" if current else str(repo_root)
    return env


def _run_capture(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run command and capture stdout/stderr."""
    proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, capture_output=True, check=False)
    if check and proc.returncode != 0:
        raise CheckerError(
            f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDOUT:\n{proc.stdout}\nSTDERR:\n{proc.stderr}"
        )
    return proc


def _run_to_file(
    cmd: list[str],
    *,
    cwd: Path,
    env: dict[str, str],
    outfile: Path,
) -> None:
    """Run command and write stdout to file."""
    with outfile.open("w", encoding="utf-8") as handle:
        proc = subprocess.run(cmd, cwd=cwd, env=env, text=True, stdout=handle, stderr=subprocess.PIPE, check=False)
    if proc.returncode != 0:
        raise CheckerError(f"Command failed ({proc.returncode}): {' '.join(cmd)}\nSTDERR:\n{proc.stderr}")


def _find_revision_files(migrations_dir: Path) -> list[Path]:
    """Return sorted migration revision files."""
    if not migrations_dir.is_dir():
        raise CheckerError(f"Migrations directory not found: {migrations_dir}")
    files = sorted(migrations_dir.glob("*.py"))
    if not files:
        raise CheckerError(f"No revision files found in: {migrations_dir}")
    return files


def _check_revision_ast(files: Iterable[Path]) -> list[str]:
    """Parse every revision file and ensure downgrade function is present."""
    problems: list[str] = []
    for path in files:
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError) as exc:
            problems.append(f"{path}: failed to read ({exc})")
            continue
        except SyntaxError as exc:
            problems.append(f"{path}:{exc.lineno or 1}: syntax error ({exc.msg})")
            continue

        has_downgrade = any(
            isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)) and node.name == "downgrade"
            for node in tree.body
        )
        if not has_downgrade:
            problems.append(f"{path}: missing downgrade()")
    return problems


def _parse_duplicate_create_type(sql_path: Path) -> list[str]:
    """Detect duplicate CREATE TYPE statements in generated SQL."""
    pattern = re.compile(r'^\s*CREATE\s+TYPE\s+("?[\w\.]+"?)\s+AS\s+ENUM', re.IGNORECASE)
    seen: dict[str, int] = {}
    duplicates: list[str] = []

    for line_no, line in enumerate(sql_path.read_text(encoding="utf-8").splitlines(), start=1):
        match = pattern.match(line)
        if not match:
            continue
        raw_name = match.group(1)
        norm_name = raw_name.replace('"', "").lower()
        if norm_name in seen:
            duplicates.append(
                f"duplicate CREATE TYPE for '{norm_name}' at lines {seen[norm_name]} and {line_no} ({sql_path})"
            )
        else:
            seen[norm_name] = line_no
    return duplicates


def _load_core_track_contract(config_path: Path) -> dict[str, str]:
    """Load core migration-track identifiers used by Alembic env contract."""
    try:
        with config_path.open("rb") as handle:
            config = tomllib.load(handle)
    except FileNotFoundError as exc:
        raise CheckerError(f"Config file not found: {config_path}") from exc
    except PermissionError as exc:
        raise CheckerError(f"Config file is not readable: {config_path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise CheckerError(f"Config file is not valid TOML: {config_path}") from exc

    if not isinstance(config, dict):
        raise CheckerError(f"Config file must parse to TOML table: {config_path}")

    tracks_cfg = config.get("rdbms", {}).get("migration_tracks", {})
    if not isinstance(tracks_cfg, dict):
        raise CheckerError("rdbms.migration_tracks must be a table")

    core_cfg = tracks_cfg.get("core", {})
    if not isinstance(core_cfg, dict):
        raise CheckerError("rdbms.migration_tracks.core must be a table")

    schema = core_cfg.get("schema")
    if schema in [None, ""]:
        raise CheckerError("rdbms.migration_tracks.core.schema is required")

    normalized_schema = _validate_identifier(
        schema,
        label="rdbms.migration_tracks.core.schema",
    )
    normalized_version_table = _validate_identifier(
        core_cfg.get("version_table", "alembic_version"),
        label="rdbms.migration_tracks.core.version_table",
    )
    normalized_version_table_schema = _validate_identifier(
        core_cfg.get("version_table_schema", normalized_schema),
        label="rdbms.migration_tracks.core.version_table_schema",
    )
    return {
        "track": "core",
        "schema": normalized_schema,
        "version_table": normalized_version_table,
        "version_table_schema": normalized_version_table_schema,
    }


def _with_core_track_env(env: dict[str, str], track: dict[str, str]) -> dict[str, str]:
    """Attach required Alembic env vars for core-track command execution."""
    resolved = dict(env)
    resolved["MUGEN_ALEMBIC_TRACK"] = track["track"]
    resolved["MUGEN_ALEMBIC_SCHEMA"] = track["schema"]
    resolved["MUGEN_ALEMBIC_VERSION_TABLE"] = track["version_table"]
    resolved["MUGEN_ALEMBIC_VERSION_TABLE_SCHEMA"] = track["version_table_schema"]
    return resolved


def _check_hardcoded_core_schema_literals(files: Iterable[Path]) -> list[str]:
    """
    Reject hardcoded core schema literals outside approved rewrite wrappers.

    Allowed:
    - import paths like `from mugen.core...`
    - plugin keys containing `com.vorsocomputing.mugen...`
    - string constants passed directly to `_sql`, `_sql_text`, `_execute`,
      or `rewrite_mugen_schema_sql`.
    """
    failures: list[str] = []

    for path in files:
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        parents: dict[ast.AST, ast.AST] = {}
        for node in ast.walk(tree):
            for child in ast.iter_child_nodes(node):
                parents[child] = node

        for node in ast.walk(tree):
            if isinstance(node, ast.Call):
                for keyword in node.keywords:
                    if keyword.arg != "schema":
                        continue
                    if (
                        isinstance(keyword.value, ast.Constant)
                        and isinstance(keyword.value.value, str)
                        and keyword.value.value.strip() == "mugen"
                    ):
                        failures.append(
                            f"{path}:{keyword.value.lineno}: hardcoded schema='mugen'"
                        )

        for node in ast.walk(tree):
            if not isinstance(node, ast.Constant) or not isinstance(node.value, str):
                continue
            value = node.value
            if "mugen." not in value:
                continue

            if "com.vorsocomputing.mugen." in value:
                continue
            if "mugen.core." in value:
                continue
            if "mugen.modules" in value:
                continue

            allowed = False
            parent = parents.get(node)
            while parent is not None:
                if isinstance(parent, ast.Call):
                    func_name = None
                    if isinstance(parent.func, ast.Name):
                        func_name = parent.func.id
                    elif isinstance(parent.func, ast.Attribute):
                        func_name = parent.func.attr
                    if func_name in {
                        "_sql",
                        "_sql_text",
                        "_execute",
                        "rewrite_mugen_schema_sql",
                    }:
                        allowed = True
                        break
                parent = parents.get(parent)

            if not allowed:
                failures.append(
                    f"{path}:{node.lineno}: hardcoded schema literal contains 'mugen.'"
                )
    return failures


def _replace_db_urls(config_path: Path, test_url: str) -> str:
    """Replace `url =` entries in mugen.toml and return original text."""
    text = config_path.read_text(encoding="utf-8")
    replaced, count = re.subn(r'(?m)^url\s*=\s*"postgresql\+psycopg://[^"]*"', f'url = "{test_url}"', text)
    if count == 0:
        raise CheckerError(f"No rdbms URL entries replaced in {config_path}")
    config_path.write_text(replaced, encoding="utf-8")
    return text


def _find_bin(name: str, fallback: str | None = None) -> str:
    """Find executable path."""
    path = shutil.which(name)
    if path:
        return path
    if fallback and Path(fallback).is_file():
        return fallback
    raise CheckerError(f"Required executable not found: {name}")


def _run_roundtrip(
    *,
    repo_root: Path,
    python_bin: str,
    alembic_config: Path,
    workdir: Path,
    config_file: Path,
    env: dict[str, str],
    core_track: dict[str, str],
    port_start: int,
    port_end: int,
    db_name: str,
) -> dict[str, str]:
    """Run upgrade head + downgrade base on a disposable Postgres cluster."""
    initdb = _find_bin("initdb", "/usr/lib/postgresql/16/bin/initdb")
    pg_ctl = _find_bin("pg_ctl", "/usr/lib/postgresql/16/bin/pg_ctl")
    createdb = _find_bin("createdb")
    psql = _find_bin("psql")

    pgdata = Path(tempfile.mkdtemp(prefix="mugen_mig_check_", dir="/tmp"))
    pglog = Path(tempfile.mkstemp(prefix="mugen_mig_check_log_", dir="/tmp")[1])

    selected_port: int | None = None
    original_config: str | None = None
    version_table_ref = (
        f"{_quote_identifier(core_track['version_table_schema'])}."
        f"{_quote_identifier(core_track['version_table'])}"
    )

    try:
        _run_capture([initdb, "-D", str(pgdata), "-A", "trust"], cwd=workdir, env=env, check=True)

        for port in range(port_start, port_end + 1):
            proc = _run_capture(
                [
                    pg_ctl,
                    "-D",
                    str(pgdata),
                    "-o",
                    f"-p {port} -c listen_addresses='' -c unix_socket_directories='/tmp'",
                    "-l",
                    str(pglog),
                    "start",
                ],
                cwd=workdir,
                env=env,
                check=False,
            )
            if proc.returncode == 0:
                selected_port = port
                break

        if selected_port is None:
            raise CheckerError(f"Could not start temporary postgres. See log: {pglog}")

        _run_capture(
            [createdb, "-h", "/tmp", "-p", str(selected_port), db_name],
            cwd=workdir,
            env=env,
            check=True,
        )

        test_url = (
            f"postgresql+psycopg://{getpass.getuser()}@/{db_name}"
            f"?host=%2Ftmp&port={selected_port}"
        )

        original_config = _replace_db_urls(config_file, test_url)

        roundtrip_env = _with_core_track_env(env, core_track)

        _run_capture(
            [python_bin, "-m", "alembic", "-c", str(alembic_config), "upgrade", "head"],
            cwd=workdir,
            env=roundtrip_env,
            check=True,
        )

        up_rev = _run_capture(
            [
                psql,
                "-h",
                "/tmp",
                "-p",
                str(selected_port),
                "-d",
                db_name,
                "-Atc",
                f"select version_num from {version_table_ref};",
            ],
            cwd=workdir,
            env=env,
            check=True,
        ).stdout.strip()

        _run_capture(
            [python_bin, "-m", "alembic", "-c", str(alembic_config), "downgrade", "base"],
            cwd=workdir,
            env=roundtrip_env,
            check=True,
        )

        down_count = _run_capture(
            [
                psql,
                "-h",
                "/tmp",
                "-p",
                str(selected_port),
                "-d",
                db_name,
                "-Atc",
                f"select count(*) from {version_table_ref};",
            ],
            cwd=workdir,
            env=env,
            check=True,
        ).stdout.strip()

        if down_count != "0":
            raise CheckerError(
                "Expected 0 rows in "
                f"{core_track['version_table_schema']}.{core_track['version_table']} "
                f"after downgrade, got: {down_count}"
            )

        return {"port": str(selected_port), "upgrade_revision": up_rev, "downgrade_version_rows": down_count}
    finally:
        if original_config is not None:
            config_file.write_text(original_config, encoding="utf-8")
        subprocess.run([pg_ctl, "-D", str(pgdata), "-m", "fast", "stop"], cwd=workdir, env=env, check=False)
        shutil.rmtree(pgdata, ignore_errors=True)


def main() -> int:
    """Run migration assessment."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo-root", default=".", help="Repository root (default: current directory).")
    parser.add_argument("--python", dest="python_bin", default=sys.executable, help="Python interpreter path.")
    parser.add_argument("--alembic-config", default="alembic.ini", help="Path to alembic config.")
    parser.add_argument("--migrations-dir", default="migrations/versions", help="Path to revision directory.")
    parser.add_argument("--config-file", default="mugen.toml", help="Config file for DB URL override in roundtrip.")
    parser.add_argument(
        "--workdir",
        default=None,
        help="Working directory for command execution (default: repo root).",
    )
    parser.add_argument("--sql-output", default=None, help="Output SQL file path (default: /tmp auto-generated).")
    parser.add_argument("--roundtrip", action="store_true", help="Run disposable postgres upgrade/downgrade test.")
    parser.add_argument("--roundtrip-port-start", type=int, default=55432, help="First port to try.")
    parser.add_argument("--roundtrip-port-end", type=int, default=55450, help="Last port to try.")
    parser.add_argument("--roundtrip-db-name", default="mugen_mig_assess", help="Disposable database name.")
    args = parser.parse_args()

    repo_root = Path(args.repo_root).resolve()
    workdir = Path(args.workdir).resolve() if args.workdir else repo_root
    alembic_config = (repo_root / args.alembic_config).resolve()
    migrations_dir = (repo_root / args.migrations_dir).resolve()
    config_file = (repo_root / args.config_file).resolve()

    try:
        core_track = _load_core_track_contract(config_file)
    except CheckerError as exc:
        print(f"ERROR: {exc}")
        return 1

    env = _with_core_track_env(_build_env(repo_root), core_track)
    failures: list[str] = []
    warnings: list[str] = []

    try:
        revision_files = _find_revision_files(migrations_dir)
    except CheckerError as exc:
        print(f"ERROR: {exc}")
        return 1

    print(f"[1/6] Checking revision AST on {len(revision_files)} files...")
    failures.extend(_check_revision_ast(revision_files))
    failures.extend(_check_hardcoded_core_schema_literals(revision_files))

    print("[2/6] Running alembic heads/history...")
    try:
        heads = _run_capture(
            [args.python_bin, "-m", "alembic", "-c", str(alembic_config), "heads"],
            cwd=workdir,
            env=env,
            check=True,
        ).stdout
        history = _run_capture(
            [args.python_bin, "-m", "alembic", "-c", str(alembic_config), "history"],
            cwd=workdir,
            env=env,
            check=True,
        ).stdout
        head_lines = [line.strip() for line in heads.splitlines() if line.strip()]
        if len(head_lines) != 1:
            failures.append(f"Expected exactly 1 alembic head, found {len(head_lines)}: {head_lines}")
        if not history.strip():
            failures.append("alembic history output is empty")
    except CheckerError as exc:
        failures.append(str(exc))

    print("[3/6] Rendering offline SQL...")
    sql_output = Path(args.sql_output).resolve() if args.sql_output else Path(
        tempfile.mkstemp(prefix="mugen_alembic_upgrade_", suffix=".sql", dir="/tmp")[1]
    )
    try:
        _run_to_file(
            [args.python_bin, "-m", "alembic", "-c", str(alembic_config), "upgrade", "head", "--sql"],
            cwd=workdir,
            env=env,
            outfile=sql_output,
        )
    except CheckerError as exc:
        failures.append(str(exc))

    print("[4/6] Scanning offline SQL for duplicate CREATE TYPE...")
    if sql_output.is_file():
        failures.extend(_parse_duplicate_create_type(sql_output))
    else:
        failures.append(f"Offline SQL output missing: {sql_output}")

    print("[5/6] Checking downgrade coverage...")
    missing_downgrades = 0
    for item in failures:
        if item.endswith("missing downgrade()"):
            missing_downgrades += 1
    if missing_downgrades:
        warnings.append(f"{missing_downgrades} revision file(s) missing downgrade()")

    roundtrip_result: dict[str, str] | None = None
    if args.roundtrip:
        print("[6/6] Running disposable postgres roundtrip...")
        try:
            roundtrip_result = _run_roundtrip(
                repo_root=repo_root,
                python_bin=args.python_bin,
                alembic_config=alembic_config,
                workdir=workdir,
                config_file=config_file,
                env=env,
                core_track=core_track,
                port_start=args.roundtrip_port_start,
                port_end=args.roundtrip_port_end,
                db_name=args.roundtrip_db_name,
            )
        except CheckerError as exc:
            failures.append(str(exc))
    else:
        print("[6/6] Skipped disposable postgres roundtrip (use --roundtrip).")

    print("\nAssessment Summary")
    print(f"- revisions parsed: {len(revision_files)}")
    print(f"- offline sql: {sql_output}")
    if roundtrip_result:
        print(
            f"- roundtrip: port {roundtrip_result['port']}, "
            f"upgrade rev {roundtrip_result['upgrade_revision']}, "
            f"downgrade version rows {roundtrip_result['downgrade_version_rows']}"
        )

    if warnings:
        print("- warnings:")
        for warning in warnings:
            print(f"  - {warning}")

    if failures:
        print("- failures:")
        for failure in failures:
            print(f"  - {failure}")
        return 1

    print("- status: PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
