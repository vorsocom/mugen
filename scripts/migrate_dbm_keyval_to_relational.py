#!/usr/bin/env python3
"""Migrate legacy DBM keyval entries into relational keyval storage."""

from __future__ import annotations

import argparse
import dbm.gnu
from datetime import UTC, datetime
import hashlib
import json
from pathlib import Path
from typing import Iterable
import tomllib

import sqlalchemy as sa
from sqlalchemy.engine import Connection, Engine

_DEFAULT_CONFIG_PATH = "mugen.toml"
_DEFAULT_NAMESPACE = "default"
_DEFAULT_META_NAMESPACE = "__meta__"
_DEFAULT_META_KEY = "legacy_dbm_import_v1"
_LOCK_NAME = "mugen:keyval:legacy-db-import:v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Copy legacy DBM key/value records into relational keyval storage "
            "using idempotent upserts."
        )
    )
    parser.add_argument(
        "--config",
        default=_DEFAULT_CONFIG_PATH,
        help=f"Path to mugen TOML config (default: {_DEFAULT_CONFIG_PATH}).",
    )
    parser.add_argument(
        "--dbm-path",
        default=None,
        help="Override legacy DBM path (defaults to mugen.storage.keyval.dbm.path).",
    )
    parser.add_argument(
        "--rdbms-url",
        default=None,
        help=(
            "Override relational DSN (defaults to rdbms.sqlalchemy.url or "
            "rdbms.alembic.url)."
        ),
    )
    parser.add_argument(
        "--schema",
        default="mugen",
        help="Target relational schema (default: mugen).",
    )
    parser.add_argument(
        "--table",
        default="core_keyval_entry",
        help="Target relational table name (default: core_keyval_entry).",
    )
    parser.add_argument(
        "--namespace",
        default=_DEFAULT_NAMESPACE,
        help=f"Namespace for migrated keys (default: {_DEFAULT_NAMESPACE}).",
    )
    parser.add_argument(
        "--meta-namespace",
        default=_DEFAULT_META_NAMESPACE,
        help=(
            "Namespace for migration marker key "
            f"(default: {_DEFAULT_META_NAMESPACE})."
        ),
    )
    parser.add_argument(
        "--meta-key",
        default=_DEFAULT_META_KEY,
        help=f"Migration marker key name (default: {_DEFAULT_META_KEY}).",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print migration summary without writing to relational storage.",
    )
    parser.add_argument(
        "--skip-meta-marker",
        action="store_true",
        help="Do not write the migration marker record after import.",
    )
    return parser.parse_args()


def _load_config(path: Path) -> dict:
    with path.open("rb") as handle:
        return tomllib.load(handle)


def _resolve_configured_path(config_path: Path, configured_path: str) -> Path:
    path = Path(configured_path)
    if path.is_absolute():
        return path
    return (config_path.parent / path).resolve()


def _resolve_dbm_path(args: argparse.Namespace, cfg: dict, config_path: Path) -> Path:
    if args.dbm_path is not None and str(args.dbm_path).strip() != "":
        return _resolve_configured_path(config_path, str(args.dbm_path).strip())

    value = (
        cfg.get("mugen", {})
        .get("storage", {})
        .get("keyval", {})
        .get("dbm", {})
        .get("path")
    )
    if not isinstance(value, str) or value.strip() == "":
        raise RuntimeError(
            "Could not resolve DBM path. Set --dbm-path or configure "
            "mugen.storage.keyval.dbm.path."
        )
    return _resolve_configured_path(config_path, value.strip())


def _resolve_rdbms_url(args: argparse.Namespace, cfg: dict) -> str:
    if args.rdbms_url is not None and str(args.rdbms_url).strip() != "":
        return str(args.rdbms_url).strip()

    sqlalchemy_url = cfg.get("rdbms", {}).get("sqlalchemy", {}).get("url")
    alembic_url = cfg.get("rdbms", {}).get("alembic", {}).get("url")
    for candidate in [sqlalchemy_url, alembic_url]:
        if isinstance(candidate, str) and candidate.strip() != "":
            return candidate.strip()

    raise RuntimeError(
        "Could not resolve relational URL. Set --rdbms-url or configure "
        "rdbms.sqlalchemy.url."
    )


def _qualified_table(schema: str, table: str) -> str:
    if schema.strip() == "":
        return table
    return f"{schema}.{table}"


def _lock_key(name: str) -> int:
    digest = hashlib.sha256(name.encode("utf-8")).digest()
    return int.from_bytes(digest[:8], byteorder="big", signed=False) % (2**63)


def _decode_dbm_key(raw_key: bytes) -> str | None:
    try:
        decoded = raw_key.decode("utf-8")
    except UnicodeDecodeError:
        return None
    return decoded if decoded != "" else None


def _infer_codec(payload: bytes) -> str:
    try:
        decoded = payload.decode("utf-8")
    except UnicodeDecodeError:
        return "binary"

    try:
        json.loads(decoded)
        return "json"
    except (TypeError, ValueError, json.JSONDecodeError):
        return "utf8"


def _iter_dbm_entries(path: Path) -> Iterable[tuple[str, bytes, str]]:
    with dbm.gnu.open(str(path), "r") as db:
        for raw_key in db.keys():
            if not isinstance(raw_key, bytes):
                continue
            key = _decode_dbm_key(raw_key)
            if key is None:
                continue
            payload = db[raw_key]
            codec = _infer_codec(payload)
            yield key, payload, codec


def _ensure_target_exists(conn: Connection, qualified_table_name: str) -> None:
    exists_query = sa.text("SELECT to_regclass(:table_name)")
    result = conn.execute(exists_query, {"table_name": qualified_table_name}).scalar()
    if result is None:
        raise RuntimeError(
            f"Target table not found: {qualified_table_name}. Run migrations first."
        )


def _acquire_lock(conn: Connection, lock_id: int) -> None:
    conn.execute(sa.text("SELECT pg_advisory_lock(:lock_id)"), {"lock_id": lock_id})


def _release_lock(conn: Connection, lock_id: int) -> None:
    conn.execute(sa.text("SELECT pg_advisory_unlock(:lock_id)"), {"lock_id": lock_id})


def _insert_entry(
    conn: Connection,
    *,
    table_name: str,
    namespace: str,
    entry_key: str,
    payload: bytes,
    codec: str,
) -> bool:
    stmt = sa.text(
        f"""
        INSERT INTO {table_name} (
            namespace,
            entry_key,
            payload,
            codec,
            expires_at
        )
        VALUES (
            :namespace,
            :entry_key,
            :payload,
            :codec,
            NULL
        )
        ON CONFLICT (namespace, entry_key) DO NOTHING
        """
    )
    result = conn.execute(
        stmt,
        {
            "namespace": namespace,
            "entry_key": entry_key,
            "payload": payload,
            "codec": codec,
        },
    )
    return result.rowcount == 1


def _upsert_marker(
    conn: Connection,
    *,
    table_name: str,
    namespace: str,
    marker_key: str,
    marker_payload: dict,
) -> None:
    stmt = sa.text(
        f"""
        INSERT INTO {table_name} (
            namespace,
            entry_key,
            payload,
            codec,
            expires_at
        )
        VALUES (
            :namespace,
            :entry_key,
            :payload,
            'json',
            NULL
        )
        ON CONFLICT (namespace, entry_key)
        DO UPDATE SET
            payload = EXCLUDED.payload,
            codec = EXCLUDED.codec,
            updated_at = now()
        """
    )
    conn.execute(
        stmt,
        {
            "namespace": namespace,
            "entry_key": marker_key,
            "payload": json.dumps(marker_payload, separators=(",", ":")).encode(
                "utf-8"
            ),
        },
    )


def _print_summary(
    *,
    dbm_path: Path,
    table_name: str,
    namespace: str,
    discovered: int,
    inserted: int,
    skipped: int,
    skipped_invalid_key: int,
    dry_run: bool,
) -> None:
    mode = "DRY-RUN" if dry_run else "APPLY"
    print(f"[{mode}] DBM path: {dbm_path}")
    print(f"[{mode}] Target table: {table_name}")
    print(f"[{mode}] Target namespace: {namespace}")
    print(
        f"[{mode}] Summary: discovered={discovered} inserted={inserted} "
        f"skipped_existing={skipped} skipped_invalid_key={skipped_invalid_key}"
    )


def main() -> int:
    args = _parse_args()
    config_path = Path(args.config).resolve()
    cfg = _load_config(config_path)

    dbm_path = _resolve_dbm_path(args, cfg, config_path)
    rdbms_url = _resolve_rdbms_url(args, cfg)
    schema = str(args.schema).strip()
    table = str(args.table).strip()
    namespace = str(args.namespace).strip()
    meta_namespace = str(args.meta_namespace).strip()
    meta_key = str(args.meta_key).strip()
    dry_run = bool(args.dry_run)

    if namespace == "":
        raise RuntimeError("--namespace cannot be empty.")
    if meta_namespace == "":
        raise RuntimeError("--meta-namespace cannot be empty.")
    if meta_key == "":
        raise RuntimeError("--meta-key cannot be empty.")
    if not dbm_path.exists():
        raise RuntimeError(f"DBM file not found: {dbm_path}")
    if table == "":
        raise RuntimeError("--table cannot be empty.")

    qualified_table_name = _qualified_table(schema, table)

    discovered = 0
    inserted = 0
    skipped_existing = 0
    skipped_invalid_key = 0

    with dbm.gnu.open(str(dbm_path), "r") as db:
        keys = db.keys()
        decoded_entries: list[tuple[str, bytes, str]] = []
        for raw_key in keys:
            if not isinstance(raw_key, bytes):
                skipped_invalid_key += 1
                continue
            decoded = _decode_dbm_key(raw_key)
            if decoded is None:
                skipped_invalid_key += 1
                continue
            payload = db[raw_key]
            decoded_entries.append((decoded, payload, _infer_codec(payload)))
        discovered = len(decoded_entries)

    if dry_run:
        _print_summary(
            dbm_path=dbm_path,
            table_name=qualified_table_name,
            namespace=namespace,
            discovered=discovered,
            inserted=discovered,
            skipped=0,
            skipped_invalid_key=skipped_invalid_key,
            dry_run=True,
        )
        return 0

    engine: Engine = sa.create_engine(rdbms_url, future=True)
    lock_id = _lock_key(_LOCK_NAME)
    timestamp = datetime.now(UTC).isoformat()

    try:
        with engine.begin() as conn:
            _ensure_target_exists(conn, qualified_table_name)
            _acquire_lock(conn, lock_id)
            try:
                for key, payload, codec in decoded_entries:
                    if _insert_entry(
                        conn,
                        table_name=qualified_table_name,
                        namespace=namespace,
                        entry_key=key,
                        payload=payload,
                        codec=codec,
                    ):
                        inserted += 1
                    else:
                        skipped_existing += 1

                if not args.skip_meta_marker:
                    marker_payload = {
                        "version": 1,
                        "source": str(dbm_path),
                        "migrated_at": timestamp,
                        "namespace": namespace,
                        "discovered": discovered,
                        "inserted": inserted,
                        "skipped_existing": skipped_existing,
                        "skipped_invalid_key": skipped_invalid_key,
                    }
                    _upsert_marker(
                        conn,
                        table_name=qualified_table_name,
                        namespace=meta_namespace,
                        marker_key=meta_key,
                        marker_payload=marker_payload,
                    )
            finally:
                _release_lock(conn, lock_id)
    finally:
        engine.dispose()

    _print_summary(
        dbm_path=dbm_path,
        table_name=qualified_table_name,
        namespace=namespace,
        discovered=discovered,
        inserted=inserted,
        skipped=skipped_existing,
        skipped_invalid_key=skipped_invalid_key,
        dry_run=False,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
