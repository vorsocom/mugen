"""Unit tests for mugen.core.gateway.storage.keyval.relational."""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
import unittest
from unittest.mock import AsyncMock, Mock, patch

from sqlalchemy.exc import SQLAlchemyError

from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValBackendError,
    KeyValConflictError,
    KeyValEntry,
    KeyValListPage,
)
from mugen.core.gateway.storage.keyval.relational import RelationalKeyValStorageGateway


class _FakeMappings:
    def __init__(self, rows):
        self._rows = list(rows)

    def one_or_none(self):
        return self._rows[0] if self._rows else None

    def one(self):
        if not self._rows:
            raise AssertionError("expected one row")
        return self._rows[0]

    def all(self):
        return list(self._rows)


class _FakeResult:
    def __init__(
        self,
        *,
        rows=None,
        scalar_value=None,
        first_value=None,
        rowcount: int | None = None,
        fetchall_rows=None,
    ):
        self._rows = list(rows or [])
        self._scalar_value = scalar_value
        self._first_value = first_value
        self.rowcount = rowcount
        self._fetchall_rows = list(fetchall_rows or [])

    def mappings(self):
        return _FakeMappings(self._rows)

    def scalar(self):
        return self._scalar_value

    def first(self):
        if self._first_value is not None:
            return self._first_value
        if self._rows:
            return self._rows[0]
        return None

    def fetchall(self):
        if self._fetchall_rows:
            return list(self._fetchall_rows)
        return list(self._rows)


class _AsyncContext:
    def __init__(self, value):
        self._value = value

    async def __aenter__(self):
        return self._value

    async def __aexit__(self, exc_type, exc, tb):  # noqa: ARG002
        return False


class _MemoryRelationalEngine:
    def __init__(self):
        self.rows: dict[tuple[str, str], dict] = {}
        self.table_exists = True
        self.disposed = False
        self.raise_exc: Exception | None = None

    def _now(self):
        from datetime import datetime, timezone

        return datetime.now(timezone.utc)

    def connect(self):
        return _AsyncContext(_MemoryRelationalConnection(self))

    def begin(self):
        return _AsyncContext(_MemoryRelationalConnection(self))

    async def dispose(self):
        self.disposed = True


class _MemoryRelationalConnection:
    def __init__(self, engine: _MemoryRelationalEngine):
        self._engine = engine

    async def execute(self, stmt, params=None):
        if self._engine.raise_exc is not None:
            raise self._engine.raise_exc
        sql = str(stmt)
        args = dict(params or {})
        now = self._engine._now()

        if "SELECT 1" in sql and "FROM mugen.core_keyval_entry" not in sql:
            return _FakeResult(scalar_value=1)

        if "to_regclass('mugen.core_keyval_entry')" in sql:
            table_name = "mugen.core_keyval_entry" if self._engine.table_exists else None
            return _FakeResult(rows=[{"table_name": table_name}])

        if "SELECT pg_advisory_lock" in sql or "SELECT pg_advisory_unlock" in sql:
            return _FakeResult()

        if "SELECT row_version FROM mugen.core_keyval_entry" in sql:
            key = (str(args.get("namespace")), str(args.get("entry_key")))
            row = self._engine.rows.get(key)
            return _FakeResult(rows=[] if row is None else [{"row_version": row["row_version"]}])

        if (
            "SELECT namespace, entry_key, payload, codec, row_version, expires_at" in sql
            and "FROM mugen.core_keyval_entry" in sql
            and "WHERE namespace = :namespace AND entry_key = :entry_key" in sql
        ):
            key = (str(args.get("namespace")), str(args.get("entry_key")))
            row = self._engine.rows.get(key)
            if row is None:
                return _FakeResult(rows=[])
            if "expires_at > now()" in sql:
                expires_at = row.get("expires_at")
                if expires_at is not None and expires_at <= now:
                    return _FakeResult(rows=[])
            return _FakeResult(rows=[dict(row)])

        if (
            "INSERT INTO mugen.core_keyval_entry" in sql
            and "row_version = mugen.core_keyval_entry.row_version + 1" in sql
        ):
            key = (str(args["namespace"]), str(args["entry_key"]))
            existing = self._engine.rows.get(key)
            if existing is None:
                row = {
                    "namespace": key[0],
                    "entry_key": key[1],
                    "payload": args["payload"],
                    "codec": args["codec"],
                    "row_version": 1,
                    "expires_at": args.get("expires_at"),
                    "created_at": now,
                    "updated_at": now,
                }
            else:
                row = dict(existing)
                row["payload"] = args["payload"]
                row["codec"] = args["codec"]
                row["expires_at"] = args.get("expires_at")
                row["updated_at"] = now
                row["row_version"] = int(existing["row_version"]) + 1
            self._engine.rows[key] = row
            return _FakeResult(rows=[dict(row)])

        if "ON CONFLICT (namespace, entry_key) DO NOTHING" in sql:
            key = (str(args["namespace"]), str(args["entry_key"]))
            if key in self._engine.rows:
                return _FakeResult(rows=[], rowcount=0)
            row = {
                "namespace": key[0],
                "entry_key": key[1],
                "payload": args["payload"],
                "codec": args["codec"],
                "row_version": 1,
                "expires_at": args.get("expires_at"),
                "created_at": now,
                "updated_at": now,
            }
            self._engine.rows[key] = row
            rows = [dict(row)] if "RETURNING" in sql else []
            return _FakeResult(rows=rows, rowcount=1)

        if (
            "UPDATE mugen.core_keyval_entry" in sql
            and "WHERE namespace = :namespace AND entry_key = :entry_key" in sql
            and "AND row_version = :expected_row_version" in sql
        ):
            key = (str(args["namespace"]), str(args["entry_key"]))
            row = self._engine.rows.get(key)
            if row is None or int(row["row_version"]) != int(args["expected_row_version"]):
                return _FakeResult(rows=[])
            updated = dict(row)
            updated["payload"] = args["payload"]
            updated["codec"] = args["codec"]
            updated["expires_at"] = args.get("expires_at")
            updated["updated_at"] = now
            updated["row_version"] = int(row["row_version"]) + 1
            self._engine.rows[key] = updated
            return _FakeResult(rows=[dict(updated)])

        if "DELETE FROM mugen.core_keyval_entry" in sql and "RETURNING" in sql:
            key = (str(args["namespace"]), str(args["entry_key"]))
            row = self._engine.rows.get(key)
            if row is None:
                return _FakeResult(rows=[])
            expected = args.get("expected_row_version")
            if expected is not None and int(row["row_version"]) != int(expected):
                return _FakeResult(rows=[])
            deleted = self._engine.rows.pop(key)
            return _FakeResult(rows=[dict(deleted)])

        if "SELECT 1 FROM mugen.core_keyval_entry" in sql:
            key = (str(args["namespace"]), str(args["entry_key"]))
            row = self._engine.rows.get(key)
            if row is None:
                return _FakeResult(first_value=None)
            expires_at = row.get("expires_at")
            if expires_at is not None and expires_at <= now:
                return _FakeResult(first_value=None)
            return _FakeResult(first_value=(1,))

        if "SELECT entry_key FROM mugen.core_keyval_entry" in sql:
            namespace = str(args["namespace"])
            prefix_like = str(args.get("prefix_like", "%"))
            prefix = prefix_like[:-1] if prefix_like.endswith("%") else prefix_like
            cursor = args.get("cursor")
            limit = int(args["limit"])
            keys = []
            for (row_namespace, row_key), row in self._engine.rows.items():
                if row_namespace != namespace:
                    continue
                expires_at = row.get("expires_at")
                if expires_at is not None and expires_at <= now:
                    continue
                if not row_key.startswith(prefix):
                    continue
                if cursor not in [None, ""] and row_key <= str(cursor):
                    continue
                keys.append(row_key)
            keys.sort()
            return _FakeResult(fetchall_rows=[(k,) for k in keys[:limit]])

        if "INSERT INTO mugen.core_keyval_entry" in sql and "ON CONFLICT (namespace, entry_key) DO UPDATE" in sql:
            key = (str(args["namespace"]), str(args["entry_key"]))
            existing = self._engine.rows.get(key)
            row_version = 1 if existing is None else int(existing["row_version"]) + 1
            row = {
                "namespace": key[0],
                "entry_key": key[1],
                "payload": args["payload"],
                "codec": "application/json",
                "row_version": row_version,
                "expires_at": None,
                "created_at": now if existing is None else existing["created_at"],
                "updated_at": now,
            }
            self._engine.rows[key] = row
            return _FakeResult(rowcount=1)

        raise AssertionError(f"Unhandled SQL in test fake engine: {sql}")


def _make_config(
    *,
    namespace_default="core",
    list_limit_default=200,
    basedir="/srv/mugen",
):
    return SimpleNamespace(
        basedir=basedir,
        rdbms=SimpleNamespace(sqlalchemy=SimpleNamespace(url="postgresql+asyncpg://test")),
        mugen=SimpleNamespace(
            storage=SimpleNamespace(
                keyval=SimpleNamespace(
                    relational=SimpleNamespace(
                        namespace_default=namespace_default,
                        list_limit_default=list_limit_default,
                    ),
                )
            )
        ),
    )


def _new_gateway(*, engine=None, config=None, logger=None):
    gateway = RelationalKeyValStorageGateway.__new__(RelationalKeyValStorageGateway)
    gateway._config = config or _make_config()
    gateway._logging_gateway = logger or Mock()
    gateway._namespace_default = "core"
    gateway._list_limit_default = 2
    gateway._closed = False
    gateway._backend_ready = True
    gateway._backend_ready_lock = None
    gateway._engine = engine or _MemoryRelationalEngine()
    return gateway


class TestMugenGatewayStorageKeyvalRelational(unittest.IsolatedAsyncioTestCase):
    """Covers async relational keyval behavior and hardening branches."""

    async def test_verify_backend_ready_success_and_failure(self) -> None:
        logger = Mock()
        engine = _MemoryRelationalEngine()
        gateway = _new_gateway(engine=engine, logger=logger)
        await gateway._verify_backend_ready()  # pylint: disable=protected-access

        engine.table_exists = False
        with self.assertRaises(RuntimeError):
            await gateway._verify_backend_ready()  # pylint: disable=protected-access
        logger.error.assert_called()

        engine.raise_exc = SQLAlchemyError("boom")
        with self.assertRaises(RuntimeError):
            await gateway._verify_backend_ready()  # pylint: disable=protected-access

    async def test_async_crud_cas_delete_exists_and_list(self) -> None:
        gateway = _new_gateway()

        first = await gateway.put_text("alpha", "one")
        self.assertEqual(first.row_version, 1)
        self.assertEqual(await gateway.get_text("alpha"), "one")

        await gateway.put_json("json", {"k": "v"})
        self.assertEqual(await gateway.get_json("json"), {"k": "v"})

        updated = await gateway.put_bytes(
            "alpha",
            b"two",
            codec="bytes",
            expected_row_version=1,
            ttl_seconds=5.0,
        )
        self.assertEqual(updated.row_version, 2)
        self.assertIsNotNone(updated.expires_at)

        inserted = await gateway.put_bytes("beta", b"value", expected_row_version=0)
        self.assertEqual(inserted.row_version, 1)

        with self.assertRaises(KeyValConflictError):
            await gateway.put_bytes("beta", b"value2", expected_row_version=0)

        with self.assertRaises(KeyValConflictError):
            await gateway.put_bytes("alpha", b"three", expected_row_version=999)

        self.assertTrue(await gateway.exists("alpha"))
        removed = await gateway.delete("alpha")
        self.assertIsNotNone(removed)
        self.assertFalse(await gateway.exists("alpha"))
        self.assertIsNone(await gateway.delete("missing"))

        with self.assertRaises(KeyValConflictError):
            await gateway.delete("beta", expected_row_version=99)

        keys_page_1 = await gateway.list_keys(prefix="", limit=1)
        keys_page_2 = await gateway.list_keys(
            prefix="",
            limit=1,
            cursor=keys_page_1.next_cursor,
        )
        self.assertEqual(len(keys_page_1.keys), 1)
        self.assertEqual(len(keys_page_2.keys), 1)

    async def test_get_entry_text_and_json_none_paths(self) -> None:
        gateway = _new_gateway()
        self.assertIsNone(await gateway.get_entry("missing"))
        self.assertIsNone(await gateway.get_text("missing"))
        self.assertIsNone(await gateway.get_json("missing"))

    async def test_put_validation_and_error_paths(self) -> None:
        gateway = _new_gateway()

        with self.assertRaises(ValueError):
            await gateway.put_text("k", 123)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            await gateway.put_bytes("k", b"v", codec="")
        with self.assertRaises(ValueError):
            await gateway.put_bytes("k", "bad")  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            await gateway.get_entry("")
        with self.assertRaises(ValueError):
            await gateway.get_entry("k", namespace=1)  # type: ignore[arg-type]
        with self.assertRaises(ValueError):
            await gateway.exists(123)  # type: ignore[arg-type]

        failing_engine = _MemoryRelationalEngine()
        failing_engine.raise_exc = SQLAlchemyError("x")
        failing_gateway = _new_gateway(engine=failing_engine)

        with self.assertRaises(KeyValBackendError):
            await failing_gateway.get_entry("x")
        with self.assertRaises(KeyValBackendError):
            await failing_gateway.put_bytes("x", b"y")
        with self.assertRaises(KeyValBackendError):
            await failing_gateway.delete("x")
        with self.assertRaises(KeyValBackendError):
            await failing_gateway.exists("x")
        with self.assertRaises(KeyValBackendError):
            await failing_gateway.list_keys()

        failing_engine_cas_insert = _MemoryRelationalEngine()
        failing_engine_cas_insert.raise_exc = SQLAlchemyError("insert-fail")
        failing_gateway_insert = _new_gateway(engine=failing_engine_cas_insert)
        with self.assertRaises(KeyValBackendError):
            await failing_gateway_insert.put_bytes("x", b"y", expected_row_version=0)

        failing_engine_cas_update = _MemoryRelationalEngine()
        failing_engine_cas_update.rows[("core", "x")] = {
            "namespace": "core",
            "entry_key": "x",
            "payload": b"v1",
            "codec": "bytes",
            "row_version": 1,
            "expires_at": None,
            "created_at": failing_engine_cas_update._now(),
            "updated_at": failing_engine_cas_update._now(),
        }
        failing_engine_cas_update.raise_exc = SQLAlchemyError("update-fail")
        failing_gateway_update = _new_gateway(engine=failing_engine_cas_update)
        with self.assertRaises(KeyValBackendError):
            await failing_gateway_update.put_bytes("x", b"v2", expected_row_version=1)

    async def test_list_keys_limits_and_compare_and_set_alias(self) -> None:
        gateway = _new_gateway()
        gateway._list_limit_default = 1  # pylint: disable=protected-access

        await gateway.put_text("p:a", "1")
        await gateway.put_text("p:b", "2")
        await gateway.put_text("q:c", "3")

        page = await gateway.list_keys(prefix="p:", limit=0)
        self.assertEqual(page.keys, ["p:a"])
        next_page = await gateway.list_keys(prefix="p:", cursor=page.next_cursor, limit=99_999)
        self.assertEqual(next_page.keys, ["p:b"])

        updated = await gateway.compare_and_set(
            "p:a",
            b"x",
            expected_row_version=1,
            codec="bytes",
        )
        self.assertEqual(updated.row_version, 2)

    async def test_aclose_and_close_idempotency(self) -> None:
        gateway = _new_gateway()

        await gateway.aclose()
        self.assertTrue(gateway._closed)  # pylint: disable=protected-access
        self.assertTrue(gateway._engine.disposed)  # pylint: disable=protected-access

        gateway._engine.disposed = False  # pylint: disable=protected-access
        await gateway.aclose()
        self.assertFalse(gateway._engine.disposed)  # pylint: disable=protected-access

class TestMugenGatewayStorageKeyvalRelationalInit(unittest.IsolatedAsyncioTestCase):
    """Covers initialization and readiness helper behavior."""

    async def test_ensure_backend_ready_runs_once(self) -> None:
        gateway = _new_gateway()
        gateway._backend_ready = False  # pylint: disable=protected-access
        gateway._verify_backend_ready = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await gateway._ensure_backend_ready()  # pylint: disable=protected-access
        await gateway._ensure_backend_ready()  # pylint: disable=protected-access

        gateway._verify_backend_ready.assert_awaited_once()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    async def test_ensure_backend_ready_returns_if_marked_ready_while_waiting(self) -> None:
        gateway = _new_gateway()
        gateway._backend_ready = False  # pylint: disable=protected-access
        gateway._verify_backend_ready = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access
        lock = asyncio.Lock()
        await lock.acquire()
        gateway._backend_ready_lock = lock  # pylint: disable=protected-access

        waiter = asyncio.create_task(gateway._ensure_backend_ready())  # pylint: disable=protected-access
        await asyncio.sleep(0)
        gateway._backend_ready = True  # pylint: disable=protected-access
        lock.release()
        await waiter

        gateway._verify_backend_ready.assert_not_awaited()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    async def test_ensure_backend_ready_rejects_closed_gateway(self) -> None:
        gateway = _new_gateway()
        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            await gateway._ensure_backend_ready()  # pylint: disable=protected-access

    async def test_check_readiness_delegates_to_backend_readiness_helper(self) -> None:
        gateway = _new_gateway()
        gateway._ensure_backend_ready = AsyncMock()  # type: ignore[method-assign]  # pylint: disable=protected-access

        await gateway.check_readiness()

        gateway._ensure_backend_ready.assert_awaited_once()  # type: ignore[attr-defined]  # pylint: disable=protected-access

    def test_init_builds_engine_and_runtime_flags(self) -> None:
        config = _make_config()
        logger = Mock()
        with patch(
            "mugen.core.gateway.storage.keyval.relational.create_async_engine",
            return_value=Mock(),
        ):
            gateway = RelationalKeyValStorageGateway(config, logger)
        self.assertFalse(gateway._closed)  # pylint: disable=protected-access
        self.assertFalse(gateway._backend_ready)  # pylint: disable=protected-access

    def test_config_resolvers_and_helpers(self) -> None:
        logger = Mock()
        gateway = _new_gateway(
            config=_make_config(
                namespace_default="  ",
                list_limit_default="bad",
                basedir="/srv/app",
            ),
            logger=logger,
        )

        self.assertEqual(gateway._resolve_namespace_default(), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_list_limit_default(), 200)  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_namespace(None), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_namespace(""), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_key(" k "), "k")  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at(None))  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at("bad"))  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at(-1))  # pylint: disable=protected-access
        self.assertIsNotNone(gateway._resolve_expires_at(1.0))  # pylint: disable=protected-access

        with self.assertRaises(ValueError):
            gateway._normalize_namespace(1)  # type: ignore[arg-type]  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_namespace("   ")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_key("")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_key(1)  # type: ignore[arg-type]  # pylint: disable=protected-access

    def test_list_limit_and_namespace_default_boundaries(self) -> None:
        logger = Mock()
        list_default_zero = _new_gateway(
            config=_make_config(list_limit_default=0),
            logger=logger,
        )
        self.assertEqual(list_default_zero._resolve_list_limit_default(), 200)  # pylint: disable=protected-access

        list_default_huge = _new_gateway(
            config=_make_config(list_limit_default=1000000),
            logger=logger,
        )
        self.assertEqual(list_default_huge._resolve_list_limit_default(), 2000)  # pylint: disable=protected-access

        namespace_non_string = _new_gateway(
            config=_make_config(namespace_default=123),  # type: ignore[arg-type]
            logger=logger,
        )
        self.assertEqual(namespace_non_string._resolve_namespace_default(), "core")  # pylint: disable=protected-access

    def test_to_entry_handles_memoryview_and_non_bytes_payload(self) -> None:

        entry_from_memoryview = RelationalKeyValStorageGateway._to_entry(  # pylint: disable=protected-access
            {
                "namespace": "core",
                "entry_key": "mv",
                "payload": memoryview(b"abc"),
                "codec": "bytes",
                "row_version": 1,
                "expires_at": None,
                "created_at": None,
                "updated_at": None,
            }
        )
        self.assertEqual(entry_from_memoryview.payload, b"abc")

        entry_from_non_bytes = RelationalKeyValStorageGateway._to_entry(  # pylint: disable=protected-access
            {
                "namespace": "core",
                "entry_key": "nbytes",
                "payload": 5,
                "codec": "bytes",
                "row_version": 1,
                "expires_at": None,
                "created_at": None,
                "updated_at": None,
            }
        )
        self.assertEqual(entry_from_non_bytes.payload, b"\x00\x00\x00\x00\x00")
