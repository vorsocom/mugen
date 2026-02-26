"""Provides a relational key-value storage gateway backed by PostgreSQL."""

__all__ = ["RelationalKeyValStorageGateway"]

import asyncio
import dbm.gnu
from datetime import datetime, timedelta, timezone
import hashlib
import json
import os
import threading
from types import SimpleNamespace
from typing import Any

from sqlalchemy import text as sa_text
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from mugen.core.contract.gateway.logging import ILoggingGateway
from mugen.core.contract.gateway.storage.keyval import IKeyValStorageGateway
from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValBackendError,
    KeyValConflictError,
    KeyValEntry,
    KeyValListPage,
)


class RelationalKeyValStorageGateway(IKeyValStorageGateway):
    """PostgreSQL-backed key-value gateway with CAS and typed async operations."""

    _default_namespace = "core"
    _default_list_limit = 200
    _max_list_limit = 2000
    _legacy_import_marker_namespace = "__meta__"
    _legacy_import_marker_key = "legacy_dbm_import_v1"
    _legacy_import_lock_name = "mugen:keyval:legacy-db-import:v1"

    def __init__(
        self,
        config: SimpleNamespace,
        logging_gateway: ILoggingGateway,
    ) -> None:
        self._config = config
        self._logging_gateway = logging_gateway
        self._namespace_default = self._resolve_namespace_default()
        self._list_limit_default = self._resolve_list_limit_default()
        self._closed = False

        self._engine: AsyncEngine = create_async_engine(
            self._config.rdbms.sqlalchemy.url,
        )

        self._sync_loop = asyncio.new_event_loop()
        self._sync_loop_ready = threading.Event()
        self._sync_thread = threading.Thread(
            target=self._run_sync_loop,
            name="mugen.keyval.relational.sync-loop",
            daemon=True,
        )
        self._sync_thread.start()
        if self._sync_loop_ready.wait(timeout=5.0) is not True:
            raise RuntimeError("Failed to initialize relational keyval sync loop.")

        # Fail fast on broken relational connectivity or missing table.
        self._run_sync(self._verify_backend_ready())
        self._run_sync(self._maybe_import_legacy_dbm())

    def _run_sync_loop(self) -> None:
        asyncio.set_event_loop(self._sync_loop)
        self._sync_loop_ready.set()
        self._sync_loop.run_forever()

    def _run_sync(self, awaitable):
        if self._closed:
            raise RuntimeError("Relational keyval gateway is closed.")
        future = asyncio.run_coroutine_threadsafe(awaitable, self._sync_loop)
        return future.result()

    def _stop_sync_loop(self) -> None:
        if self._sync_loop.is_running():
            self._sync_loop.call_soon_threadsafe(self._sync_loop.stop)
        if self._sync_thread.is_alive():
            self._sync_thread.join(timeout=5.0)

    async def _verify_backend_ready(self) -> None:
        try:
            async with self._engine.connect() as conn:
                await conn.execute(sa_text("SELECT 1"))
                result = await conn.execute(
                    sa_text("SELECT to_regclass('mugen.core_keyval_entry') AS table_name")
                )
                row = result.mappings().one_or_none()
                table_name = None if row is None else row.get("table_name")
                if table_name in [None, ""]:
                    raise RuntimeError(
                        "Required table mugen.core_keyval_entry was not found. "
                        "Run migrations before booting relational keyval."
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Relational keyval backend failed readiness checks."
            )
            raise RuntimeError("Relational keyval backend is unavailable.") from exc

    def _legacy_import_enabled(self) -> bool:
        raw = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "legacy_import",
                SimpleNamespace(),
            ),
            "enabled",
            False,
        )
        return bool(raw)

    def _resolve_legacy_import_dbm_path(self) -> str:
        legacy_import_cfg = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "legacy_import",
                SimpleNamespace(),
            ),
            "dbm_path",
            None,
        )
        dbm_cfg_path = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "dbm",
                SimpleNamespace(),
            ),
            "path",
            None,
        )

        candidate = legacy_import_cfg
        if not isinstance(candidate, str) or candidate.strip() == "":
            candidate = dbm_cfg_path

        if not isinstance(candidate, str) or candidate.strip() == "":
            raise RuntimeError(
                "Legacy keyval import is enabled but no DBM path is configured."
            )

        path = candidate.strip()
        if os.path.isabs(path):
            return path

        basedir = getattr(self._config, "basedir", None)
        if isinstance(basedir, str) and basedir != "":
            return os.path.abspath(os.path.join(basedir, path))
        return os.path.abspath(path)

    @staticmethod
    def _legacy_import_lock_id(lock_name: str) -> int:
        digest = hashlib.sha256(lock_name.encode("utf-8")).digest()
        return int.from_bytes(digest[:8], byteorder="big", signed=False) % (2**63)

    @staticmethod
    def _read_dbm_entries(path: str) -> list[tuple[str, bytes, str]]:
        entries: list[tuple[str, bytes, str]] = []
        with dbm.gnu.open(path, "r") as db:
            for raw_key in db.keys():
                if not isinstance(raw_key, bytes):
                    continue

                try:
                    key = raw_key.decode("utf-8")
                except UnicodeDecodeError:
                    continue

                if key == "":
                    continue

                payload = db[raw_key]
                codec = "bytes"
                try:
                    payload.decode("utf-8")
                    codec = "text/utf-8"
                except UnicodeDecodeError:
                    codec = "bytes"

                entries.append((key, payload, codec))

        return entries

    async def _maybe_import_legacy_dbm(self) -> None:
        if self._legacy_import_enabled() is not True:
            return

        dbm_path = self._resolve_legacy_import_dbm_path()
        if os.path.exists(dbm_path) is not True:
            self._logging_gateway.info(
                "Legacy keyval DBM file not found; skipping startup import "
                f"path={dbm_path!r}."
            )
            return

        lock_id = self._legacy_import_lock_id(self._legacy_import_lock_name)

        try:
            async with self._engine.begin() as conn:
                await conn.execute(
                    sa_text("SELECT pg_advisory_lock(:lock_id)"),
                    {"lock_id": lock_id},
                )

                try:
                    marker_result = await conn.execute(
                        sa_text(
                            "SELECT row_version "
                            "FROM mugen.core_keyval_entry "
                            "WHERE namespace = :namespace "
                            "AND entry_key = :entry_key"
                        ),
                        {
                            "namespace": self._legacy_import_marker_namespace,
                            "entry_key": self._legacy_import_marker_key,
                        },
                    )
                    marker_row = marker_result.mappings().one_or_none()
                    if marker_row is not None:
                        self._logging_gateway.info(
                            "Legacy keyval import marker found; skipping startup import."
                        )
                        return

                    entries = self._read_dbm_entries(dbm_path)
                    inserted = 0
                    skipped_existing = 0

                    for key, payload, codec in entries:
                        insert_result = await conn.execute(
                            sa_text(
                                "INSERT INTO mugen.core_keyval_entry "
                                "(namespace, entry_key, payload, codec, expires_at) "
                                "VALUES (:namespace, :entry_key, :payload, :codec, NULL) "
                                "ON CONFLICT (namespace, entry_key) DO NOTHING"
                            ),
                            {
                                "namespace": self._namespace_default,
                                "entry_key": key,
                                "payload": payload,
                                "codec": codec,
                            },
                        )

                        if int(insert_result.rowcount or 0) == 1:
                            inserted += 1
                        else:
                            skipped_existing += 1

                    marker_payload = json.dumps(
                        {
                            "version": 1,
                            "source": "legacy_dbm_import",
                            "dbm_path": dbm_path,
                            "namespace": self._namespace_default,
                            "discovered": len(entries),
                            "inserted": inserted,
                            "skipped_existing": skipped_existing,
                            "completed_at": datetime.now(timezone.utc).isoformat(),
                        },
                        ensure_ascii=True,
                        separators=(",", ":"),
                    ).encode("utf-8")

                    await conn.execute(
                        sa_text(
                            "INSERT INTO mugen.core_keyval_entry "
                            "(namespace, entry_key, payload, codec, expires_at) "
                            "VALUES (:namespace, :entry_key, :payload, 'application/json', NULL) "
                            "ON CONFLICT (namespace, entry_key) DO UPDATE "
                            "SET payload = EXCLUDED.payload, "
                            "codec = EXCLUDED.codec, "
                            "updated_at = now()"
                        ),
                        {
                            "namespace": self._legacy_import_marker_namespace,
                            "entry_key": self._legacy_import_marker_key,
                            "payload": marker_payload,
                        },
                    )

                    self._logging_gateway.info(
                        "Legacy keyval startup import completed."
                        f" discovered={len(entries)} inserted={inserted}"
                        f" skipped_existing={skipped_existing}"
                    )
                finally:
                    await conn.execute(
                        sa_text("SELECT pg_advisory_unlock(:lock_id)"),
                        {"lock_id": lock_id},
                    )
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self._logging_gateway.error(
                "Legacy keyval startup import failed."
                f" error={type(exc).__name__}: {exc}"
            )
            raise RuntimeError("Legacy keyval startup import failed.") from exc

    def _resolve_namespace_default(self) -> str:
        namespace = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "relational",
                SimpleNamespace(),
            ),
            "namespace_default",
            self._default_namespace,
        )
        if not isinstance(namespace, str):
            return self._default_namespace
        namespace = namespace.strip()
        if namespace == "":
            return self._default_namespace
        return namespace

    def _resolve_list_limit_default(self) -> int:
        raw_limit = getattr(
            getattr(
                getattr(
                    getattr(
                        getattr(self._config, "mugen", SimpleNamespace()),
                        "storage",
                        SimpleNamespace(),
                    ),
                    "keyval",
                    SimpleNamespace(),
                ),
                "relational",
                SimpleNamespace(),
            ),
            "list_limit_default",
            self._default_list_limit,
        )
        try:
            parsed = int(raw_limit)
        except (TypeError, ValueError):
            parsed = self._default_list_limit
        if parsed <= 0:
            return self._default_list_limit
        if parsed > self._max_list_limit:
            return self._max_list_limit
        return parsed

    def _normalize_namespace(self, namespace: str | None) -> str:
        target = self._namespace_default if namespace in [None, ""] else namespace
        if not isinstance(target, str):
            raise ValueError("namespace must be a string")
        target = target.strip()
        if target == "":
            raise ValueError("namespace must be a non-empty string")
        return target

    @staticmethod
    def _normalize_key(key: str) -> str:
        if not isinstance(key, str):
            raise ValueError("key must be a string")
        key = key.strip()
        if key == "":
            raise ValueError("key must be a non-empty string")
        return key

    @staticmethod
    def _coerce_payload(value: str | bytes) -> tuple[bytes, str]:
        if isinstance(value, bytes):
            return value, "bytes"
        if isinstance(value, str):
            return value.encode("utf-8"), "text/utf-8"
        raise ValueError("value must be str or bytes")

    @staticmethod
    def _to_entry(row: dict[str, Any]) -> KeyValEntry:
        payload = row.get("payload")
        if isinstance(payload, memoryview):
            payload = payload.tobytes()
        if not isinstance(payload, bytes):
            payload = bytes(payload or b"")

        return KeyValEntry(
            namespace=str(row.get("namespace")),
            key=str(row.get("entry_key")),
            payload=payload,
            codec=str(row.get("codec") or "bytes"),
            row_version=int(row.get("row_version") or 1),
            expires_at=row.get("expires_at"),
            created_at=row.get("created_at"),
            updated_at=row.get("updated_at"),
        )

    @staticmethod
    def _resolve_expires_at(ttl_seconds: float | None) -> datetime | None:
        if ttl_seconds in [None, 0]:
            return None
        try:
            ttl = float(ttl_seconds)
        except (TypeError, ValueError):
            return None
        if ttl <= 0:
            return None
        return datetime.now(timezone.utc) + timedelta(seconds=ttl)

    async def _get_entry_internal(
        self,
        *,
        namespace: str,
        key: str,
        include_expired: bool,
    ) -> KeyValEntry | None:
        where_expiry = ""
        if include_expired is not True:
            where_expiry = " AND (expires_at IS NULL OR expires_at > now())"

        stmt = sa_text(
            "SELECT namespace, entry_key, payload, codec, row_version, expires_at, "
            "created_at, updated_at "
            "FROM mugen.core_keyval_entry "
            "WHERE namespace = :namespace AND entry_key = :entry_key"
            f"{where_expiry}"
        )
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(
                    stmt,
                    {"namespace": namespace, "entry_key": key},
                )
                row = result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise KeyValBackendError(
                f"Failed to read key namespace={namespace!r} key={key!r}."
            ) from exc

        if row is None:
            return None
        return self._to_entry(dict(row))

    async def get_entry(
        self,
        key: str,
        *,
        namespace: str | None = None,
        include_expired: bool = False,
    ) -> KeyValEntry | None:
        target_namespace = self._normalize_namespace(namespace)
        target_key = self._normalize_key(key)
        return await self._get_entry_internal(
            namespace=target_namespace,
            key=target_key,
            include_expired=include_expired,
        )

    async def get_text(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> str | None:
        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            return None
        return entry.as_text()

    async def get_json(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> dict[str, Any] | list[Any] | None:
        entry = await self.get_entry(key, namespace=namespace)
        if entry is None:
            return None
        return entry.as_json()

    async def put_text(
        self,
        key: str,
        value: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        if not isinstance(value, str):
            raise ValueError("value must be a string")
        return await self.put_bytes(
            key,
            value.encode("utf-8"),
            namespace=namespace,
            codec="text/utf-8",
            expected_row_version=expected_row_version,
            ttl_seconds=ttl_seconds,
        )

    async def put_json(
        self,
        key: str,
        value: dict[str, Any] | list[Any],
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        encoded = json.dumps(value, ensure_ascii=True, separators=(",", ":")).encode(
            "utf-8"
        )
        return await self.put_bytes(
            key,
            encoded,
            namespace=namespace,
            codec="application/json",
            expected_row_version=expected_row_version,
            ttl_seconds=ttl_seconds,
        )

    async def put_bytes(
        self,
        key: str,
        value: bytes,
        *,
        namespace: str | None = None,
        codec: str = "bytes",
        expected_row_version: int | None = None,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        target_namespace = self._normalize_namespace(namespace)
        target_key = self._normalize_key(key)
        if not isinstance(value, bytes):
            raise ValueError("value must be bytes")
        if not isinstance(codec, str) or codec.strip() == "":
            raise ValueError("codec must be a non-empty string")

        expires_at = self._resolve_expires_at(ttl_seconds)

        if expected_row_version is None:
            stmt = sa_text(
                "INSERT INTO mugen.core_keyval_entry "
                "(namespace, entry_key, payload, codec, expires_at) "
                "VALUES (:namespace, :entry_key, :payload, :codec, :expires_at) "
                "ON CONFLICT (namespace, entry_key) DO UPDATE "
                "SET payload = EXCLUDED.payload, "
                "codec = EXCLUDED.codec, "
                "expires_at = EXCLUDED.expires_at, "
                "updated_at = now(), "
                "row_version = mugen.core_keyval_entry.row_version + 1 "
                "RETURNING namespace, entry_key, payload, codec, row_version, "
                "expires_at, created_at, updated_at"
            )
            params = {
                "namespace": target_namespace,
                "entry_key": target_key,
                "payload": value,
                "codec": codec.strip(),
                "expires_at": expires_at,
            }
            try:
                async with self._engine.begin() as conn:
                    result = await conn.execute(stmt, params)
                    row = result.mappings().one()
                    return self._to_entry(dict(row))
            except SQLAlchemyError as exc:
                raise KeyValBackendError(
                    f"Failed to put key namespace={target_namespace!r} "
                    f"key={target_key!r}."
                ) from exc

        expected = int(expected_row_version)
        if expected <= 0:
            stmt_insert = sa_text(
                "INSERT INTO mugen.core_keyval_entry "
                "(namespace, entry_key, payload, codec, expires_at) "
                "VALUES (:namespace, :entry_key, :payload, :codec, :expires_at) "
                "ON CONFLICT (namespace, entry_key) DO NOTHING "
                "RETURNING namespace, entry_key, payload, codec, row_version, "
                "expires_at, created_at, updated_at"
            )
            params_insert = {
                "namespace": target_namespace,
                "entry_key": target_key,
                "payload": value,
                "codec": codec.strip(),
                "expires_at": expires_at,
            }
            try:
                async with self._engine.begin() as conn:
                    result = await conn.execute(stmt_insert, params_insert)
                    row = result.mappings().one_or_none()
            except SQLAlchemyError as exc:
                raise KeyValBackendError(
                    f"Failed to CAS-insert key namespace={target_namespace!r} "
                    f"key={target_key!r}."
                ) from exc

            if row is None:
                current = await self._get_entry_internal(
                    namespace=target_namespace,
                    key=target_key,
                    include_expired=True,
                )
                raise KeyValConflictError(
                    namespace=target_namespace,
                    key=target_key,
                    expected_row_version=expected,
                    current_row_version=(
                        None if current is None else int(current.row_version)
                    ),
                )

            return self._to_entry(dict(row))

        stmt_update = sa_text(
            "UPDATE mugen.core_keyval_entry "
            "SET payload = :payload, "
            "codec = :codec, "
            "expires_at = :expires_at, "
            "updated_at = now(), "
            "row_version = row_version + 1 "
            "WHERE namespace = :namespace AND entry_key = :entry_key "
            "AND row_version = :expected_row_version "
            "RETURNING namespace, entry_key, payload, codec, row_version, "
            "expires_at, created_at, updated_at"
        )
        params_update = {
            "namespace": target_namespace,
            "entry_key": target_key,
            "payload": value,
            "codec": codec.strip(),
            "expires_at": expires_at,
            "expected_row_version": expected,
        }
        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(stmt_update, params_update)
                row = result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise KeyValBackendError(
                f"Failed to CAS-update key namespace={target_namespace!r} "
                f"key={target_key!r}."
            ) from exc

        if row is None:
            current = await self._get_entry_internal(
                namespace=target_namespace,
                key=target_key,
                include_expired=True,
            )
            raise KeyValConflictError(
                namespace=target_namespace,
                key=target_key,
                expected_row_version=expected,
                current_row_version=(None if current is None else int(current.row_version)),
            )

        return self._to_entry(dict(row))

    async def compare_and_set(
        self,
        key: str,
        value: bytes,
        *,
        namespace: str | None = None,
        codec: str = "bytes",
        expected_row_version: int,
        ttl_seconds: float | None = None,
    ) -> KeyValEntry:
        return await self.put_bytes(
            key,
            value,
            namespace=namespace,
            codec=codec,
            expected_row_version=expected_row_version,
            ttl_seconds=ttl_seconds,
        )

    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
    ) -> KeyValEntry | None:
        target_namespace = self._normalize_namespace(namespace)
        target_key = self._normalize_key(key)

        params = {
            "namespace": target_namespace,
            "entry_key": target_key,
        }

        where_row_version = ""
        if expected_row_version is not None:
            params["expected_row_version"] = int(expected_row_version)
            where_row_version = " AND row_version = :expected_row_version"

        stmt = sa_text(
            "DELETE FROM mugen.core_keyval_entry "
            "WHERE namespace = :namespace AND entry_key = :entry_key"
            f"{where_row_version}"
            " RETURNING namespace, entry_key, payload, codec, row_version, "
            "expires_at, created_at, updated_at"
        )

        try:
            async with self._engine.begin() as conn:
                result = await conn.execute(stmt, params)
                row = result.mappings().one_or_none()
        except SQLAlchemyError as exc:
            raise KeyValBackendError(
                f"Failed to delete key namespace={target_namespace!r} "
                f"key={target_key!r}."
            ) from exc

        if row is None:
            if expected_row_version is None:
                return None

            current = await self._get_entry_internal(
                namespace=target_namespace,
                key=target_key,
                include_expired=True,
            )
            raise KeyValConflictError(
                namespace=target_namespace,
                key=target_key,
                expected_row_version=int(expected_row_version),
                current_row_version=(None if current is None else int(current.row_version)),
            )

        return self._to_entry(dict(row))

    async def exists(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> bool:
        target_namespace = self._normalize_namespace(namespace)
        target_key = self._normalize_key(key)

        stmt = sa_text(
            "SELECT 1 "
            "FROM mugen.core_keyval_entry "
            "WHERE namespace = :namespace "
            "AND entry_key = :entry_key "
            "AND (expires_at IS NULL OR expires_at > now()) "
            "LIMIT 1"
        )
        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(
                    stmt,
                    {
                        "namespace": target_namespace,
                        "entry_key": target_key,
                    },
                )
                row = result.first()
        except SQLAlchemyError as exc:
            raise KeyValBackendError(
                f"Failed to check key existence namespace={target_namespace!r} "
                f"key={target_key!r}."
            ) from exc

        return row is not None

    async def list_keys(
        self,
        *,
        prefix: str = "",
        namespace: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> KeyValListPage:
        target_namespace = self._normalize_namespace(namespace)
        safe_prefix = "" if not isinstance(prefix, str) else prefix
        page_limit = self._list_limit_default if limit is None else int(limit)
        if page_limit <= 0:
            page_limit = self._list_limit_default
        if page_limit > self._max_list_limit:
            page_limit = self._max_list_limit

        filters = [
            "namespace = :namespace",
            "(expires_at IS NULL OR expires_at > now())",
        ]
        params: dict[str, Any] = {
            "namespace": target_namespace,
            "prefix_like": f"{safe_prefix}%",
            "limit": page_limit + 1,
        }

        filters.append("entry_key LIKE :prefix_like")

        if cursor not in [None, ""]:
            filters.append("entry_key > :cursor")
            params["cursor"] = str(cursor)

        where_clause = " AND ".join(filters)
        stmt = sa_text(
            "SELECT entry_key "
            "FROM mugen.core_keyval_entry "
            f"WHERE {where_clause} "
            "ORDER BY entry_key ASC "
            "LIMIT :limit"
        )

        try:
            async with self._engine.connect() as conn:
                result = await conn.execute(stmt, params)
                rows = [str(item[0]) for item in result.fetchall()]
        except SQLAlchemyError as exc:
            raise KeyValBackendError(
                f"Failed to list keys namespace={target_namespace!r}."
            ) from exc

        has_more = len(rows) > page_limit
        keys = rows[:page_limit]
        next_cursor = keys[-1] if has_more and keys else None
        return KeyValListPage(keys=keys, next_cursor=next_cursor)

    async def aclose(self) -> None:
        if self._closed:
            return
        try:
            await self._engine.dispose()
        finally:
            self._closed = True
            self._stop_sync_loop()

    def close(self) -> None:
        if self._closed:
            return
        try:
            self._run_sync(self._engine.dispose())
        finally:
            self._closed = True
            self._stop_sync_loop()

    # Legacy sync contract compatibility.
    def get(self, key: str, decode: bool = True) -> str | bytes | None:
        entry = self._run_sync(self.get_entry(key))
        if entry is None:
            return None
        if decode is not True:
            return entry.payload
        return entry.as_text()

    def has_key(self, key: str) -> bool:
        return bool(self._run_sync(self.exists(key)))

    def keys(self) -> list[str]:
        collected: list[str] = []
        cursor: str | None = None
        while True:
            page = self._run_sync(
                self.list_keys(
                    prefix="",
                    limit=self._list_limit_default,
                    cursor=cursor,
                )
            )
            collected += page.keys
            if page.next_cursor in [None, ""]:
                break
            if page.next_cursor == cursor:
                break
            cursor = page.next_cursor
        return collected

    def put(self, key: str, value: str | bytes) -> None:
        payload, codec = self._coerce_payload(value)
        self._run_sync(
            self.put_bytes(
                key,
                payload,
                codec=codec,
            )
        )

    def remove(self, key: str) -> str | bytes | None:
        removed = self._run_sync(self.delete(key))
        if removed is None:
            return None
        return removed.payload
