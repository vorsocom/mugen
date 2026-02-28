"""Provides a relational key-value storage gateway backed by PostgreSQL."""

__all__ = ["RelationalKeyValStorageGateway"]

import asyncio
from datetime import datetime, timedelta, timezone
import json
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
        self._backend_ready = False
        self._backend_ready_lock: asyncio.Lock | None = None

        self._engine: AsyncEngine = create_async_engine(
            self._config.rdbms.sqlalchemy.url,
        )

    def _assert_open(self) -> None:
        if self._closed:
            raise RuntimeError("Relational keyval gateway is closed.")

    async def _ensure_backend_ready(self) -> None:
        self._assert_open()
        if self._backend_ready is True:
            return
        if self._backend_ready_lock is None:
            self._backend_ready_lock = asyncio.Lock()
        async with self._backend_ready_lock:
            if self._backend_ready is True:
                return
            await self._verify_backend_ready()
            self._backend_ready = True

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
        await self._ensure_backend_ready()
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
        await self._ensure_backend_ready()
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
        await self._ensure_backend_ready()
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
        await self._ensure_backend_ready()
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
        await self._ensure_backend_ready()
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
