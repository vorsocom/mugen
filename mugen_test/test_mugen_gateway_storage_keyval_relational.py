"""Unit tests for mugen.core.gateway.storage.keyval.relational."""

from __future__ import annotations

import asyncio
import os
from types import SimpleNamespace
import threading
import unittest
from unittest.mock import Mock, patch

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


class _FakeLoop:
    def __init__(self, *, running: bool):
        self._running = running
        self.stop_called = False

    def is_running(self):
        return self._running

    def call_soon_threadsafe(self, fn):
        self.stop_called = True
        fn()

    def stop(self):
        self.stop_called = True


class _FakeThread:
    def __init__(self, *, alive: bool):
        self._alive = alive
        self.join_called = False

    def is_alive(self):
        return self._alive

    def join(self, timeout=None):  # noqa: ARG002
        self.join_called = True

    def start(self):
        return None


def _make_config(
    *,
    namespace_default="core",
    list_limit_default=200,
    legacy_import_enabled=False,
    legacy_import_dbm_path=None,
    dbm_path="storage.db",
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
                    legacy_import=SimpleNamespace(
                        enabled=legacy_import_enabled,
                        dbm_path=legacy_import_dbm_path,
                    ),
                    dbm=SimpleNamespace(path=dbm_path),
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
    gateway._engine = engine or _MemoryRelationalEngine()
    gateway._sync_loop = _FakeLoop(running=False)
    gateway._sync_loop_ready = threading.Event()
    gateway._sync_thread = _FakeThread(alive=False)
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
        gateway._stop_sync_loop = Mock()  # pylint: disable=protected-access

        await gateway.aclose()
        self.assertTrue(gateway._closed)  # pylint: disable=protected-access
        gateway._stop_sync_loop.assert_called_once()  # pylint: disable=protected-access

        gateway._stop_sync_loop.reset_mock()  # pylint: disable=protected-access
        await gateway.aclose()
        gateway._stop_sync_loop.assert_not_called()  # pylint: disable=protected-access

    async def test_legacy_import_paths(self) -> None:
        disabled_gateway = _new_gateway(
            engine=_MemoryRelationalEngine(),
            config=_make_config(legacy_import_enabled=False),
            logger=Mock(),
        )
        await disabled_gateway._maybe_import_legacy_dbm()  # pylint: disable=protected-access

        logger = Mock()
        engine = _MemoryRelationalEngine()
        engine.rows[("core", "legacy")] = {
            "namespace": "core",
            "entry_key": "legacy",
            "payload": b"existing",
            "codec": "bytes",
            "row_version": 1,
            "expires_at": None,
            "created_at": engine._now(),
            "updated_at": engine._now(),
        }
        config = _make_config(
            legacy_import_enabled=True,
            legacy_import_dbm_path="/tmp/legacy.db",
        )
        gateway = _new_gateway(engine=engine, config=config, logger=logger)

        with patch("mugen.core.gateway.storage.keyval.relational.os.path.exists", return_value=False):
            await gateway._maybe_import_legacy_dbm()  # pylint: disable=protected-access
        logger.info.assert_called()

        logger.reset_mock()
        with (
            patch("mugen.core.gateway.storage.keyval.relational.os.path.exists", return_value=True),
            patch.object(
                gateway,
                "_read_dbm_entries",  # pylint: disable=protected-access
                return_value=[
                    ("legacy", b"payload", "bytes"),
                    ("fresh", b"payload-new", "bytes"),
                ],
            ),
        ):
            await gateway._maybe_import_legacy_dbm()  # pylint: disable=protected-access

        migrated = engine.rows.get(("core", "legacy"))
        migrated_fresh = engine.rows.get(("core", "fresh"))
        marker = engine.rows.get(("__meta__", "legacy_dbm_import_v1"))
        self.assertIsNotNone(migrated)
        self.assertIsNotNone(migrated_fresh)
        self.assertIsNotNone(marker)
        self.assertEqual(migrated["payload"], b"existing")
        self.assertEqual(migrated_fresh["payload"], b"payload-new")
        self.assertEqual(marker["codec"], "application/json")

        logger.reset_mock()
        with (
            patch("mugen.core.gateway.storage.keyval.relational.os.path.exists", return_value=True),
            patch.object(
                gateway,
                "_read_dbm_entries",  # pylint: disable=protected-access
                side_effect=AssertionError("legacy import should be skipped when marker exists"),
            ),
        ):
            await gateway._maybe_import_legacy_dbm()  # pylint: disable=protected-access
        logger.info.assert_called_with(
            "Legacy keyval import marker found; skipping startup import."
        )

        failing_gateway = _new_gateway(engine=_MemoryRelationalEngine(), config=config, logger=Mock())
        with (
            patch("mugen.core.gateway.storage.keyval.relational.os.path.exists", return_value=True),
            patch.object(
                failing_gateway,
                "_read_dbm_entries",  # pylint: disable=protected-access
                side_effect=RuntimeError("bad dbm"),
            ),
            self.assertRaises(RuntimeError),
        ):
            await failing_gateway._maybe_import_legacy_dbm()  # pylint: disable=protected-access


class TestMugenGatewayStorageKeyvalRelationalSync(unittest.TestCase):
    """Covers sync compatibility wrappers and init helper branches."""

    def test_init_success_and_sync_loop_not_ready(self) -> None:
        config = _make_config()
        logger = Mock()

        class _ReadyEvent:
            def wait(self, timeout=None):  # noqa: ARG002
                return True

            def set(self):
                return None

        class _NotReadyEvent(_ReadyEvent):
            def wait(self, timeout=None):  # noqa: ARG002
                return False

        def _consume_awaitable(awaitable):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return None

        with (
            patch("mugen.core.gateway.storage.keyval.relational.create_async_engine", return_value=Mock()),
            patch("mugen.core.gateway.storage.keyval.relational.threading.Event", _ReadyEvent),
            patch("mugen.core.gateway.storage.keyval.relational.threading.Thread", return_value=_FakeThread(alive=False)),
            patch.object(RelationalKeyValStorageGateway, "_run_sync_loop", lambda self: self._sync_loop_ready.set()),
            patch.object(RelationalKeyValStorageGateway, "_run_sync", side_effect=_consume_awaitable),
        ):
            gateway = RelationalKeyValStorageGateway(config, logger)
            self.assertFalse(gateway._closed)  # pylint: disable=protected-access

        with (
            patch("mugen.core.gateway.storage.keyval.relational.create_async_engine", return_value=Mock()),
            patch("mugen.core.gateway.storage.keyval.relational.threading.Event", _NotReadyEvent),
            patch("mugen.core.gateway.storage.keyval.relational.threading.Thread", return_value=_FakeThread(alive=False)),
            patch.object(RelationalKeyValStorageGateway, "_run_sync_loop", lambda self: None),
            self.assertRaises(RuntimeError),
        ):
            RelationalKeyValStorageGateway(config, logger)

    def test_run_sync_and_stop_sync_loop_branches(self) -> None:
        gateway = _new_gateway()
        gateway._closed = True  # pylint: disable=protected-access
        with self.assertRaises(RuntimeError):
            gateway._run_sync(None)  # pylint: disable=protected-access

        gateway._closed = False  # pylint: disable=protected-access
        with patch(
            "mugen.core.gateway.storage.keyval.relational.asyncio.run_coroutine_threadsafe",
            return_value=SimpleNamespace(result=lambda: "ok"),
        ):
            self.assertEqual(gateway._run_sync(object()), "ok")  # pylint: disable=protected-access

        running_gateway = _new_gateway()
        running_gateway._sync_loop = _FakeLoop(running=True)  # pylint: disable=protected-access
        running_gateway._sync_thread = _FakeThread(alive=True)  # pylint: disable=protected-access
        running_gateway._stop_sync_loop()  # pylint: disable=protected-access
        self.assertTrue(running_gateway._sync_loop.stop_called)  # pylint: disable=protected-access
        self.assertTrue(running_gateway._sync_thread.join_called)  # pylint: disable=protected-access

        non_running_gateway = _new_gateway()
        non_running_gateway._sync_loop = _FakeLoop(running=False)  # pylint: disable=protected-access
        non_running_gateway._sync_thread = _FakeThread(alive=True)  # pylint: disable=protected-access
        non_running_gateway._stop_sync_loop()  # pylint: disable=protected-access
        self.assertFalse(non_running_gateway._sync_loop.stop_called)  # pylint: disable=protected-access
        self.assertTrue(non_running_gateway._sync_thread.join_called)  # pylint: disable=protected-access

        no_thread_gateway = _new_gateway()
        no_thread_gateway._sync_loop = _FakeLoop(running=False)  # pylint: disable=protected-access
        no_thread_gateway._sync_thread = _FakeThread(alive=False)  # pylint: disable=protected-access
        no_thread_gateway._stop_sync_loop()  # pylint: disable=protected-access
        self.assertFalse(no_thread_gateway._sync_thread.join_called)  # pylint: disable=protected-access

    def test_config_resolvers_and_helpers(self) -> None:
        logger = Mock()
        gateway = _new_gateway(
            config=_make_config(
                namespace_default="  ",
                list_limit_default="bad",
                legacy_import_enabled=True,
                legacy_import_dbm_path="relative.db",
                dbm_path="dbm.db",
                basedir="/srv/app",
            ),
            logger=logger,
        )

        self.assertEqual(gateway._resolve_namespace_default(), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._resolve_list_limit_default(), 200)  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_namespace(None), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_namespace(""), "core")  # pylint: disable=protected-access
        self.assertEqual(gateway._normalize_key(" k "), "k")  # pylint: disable=protected-access
        self.assertEqual(gateway._coerce_payload("x"), (b"x", "text/utf-8"))  # pylint: disable=protected-access
        self.assertEqual(gateway._coerce_payload(b"x"), (b"x", "bytes"))  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at(None))  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at("bad"))  # pylint: disable=protected-access
        self.assertIsNone(gateway._resolve_expires_at(-1))  # pylint: disable=protected-access
        self.assertIsNotNone(gateway._resolve_expires_at(1.0))  # pylint: disable=protected-access
        self.assertEqual(
            gateway._resolve_legacy_import_dbm_path(),  # pylint: disable=protected-access
            os.path.abspath("/srv/app/relative.db"),
        )

        with self.assertRaises(ValueError):
            gateway._normalize_namespace(1)  # type: ignore[arg-type]  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_namespace("   ")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_key("")  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._normalize_key(1)  # type: ignore[arg-type]  # pylint: disable=protected-access
        with self.assertRaises(ValueError):
            gateway._coerce_payload(1)  # type: ignore[arg-type]  # pylint: disable=protected-access

        missing_path_gateway = _new_gateway(
            config=_make_config(
                legacy_import_enabled=True,
                legacy_import_dbm_path="",
                dbm_path="",
            ),
            logger=logger,
        )
        with self.assertRaises(RuntimeError):
            missing_path_gateway._resolve_legacy_import_dbm_path()  # pylint: disable=protected-access

        absolute_path_gateway = _new_gateway(
            config=_make_config(
                legacy_import_enabled=True,
                legacy_import_dbm_path="/tmp/legacy.db",
                dbm_path="fallback.db",
            ),
            logger=logger,
        )
        self.assertEqual(
            absolute_path_gateway._resolve_legacy_import_dbm_path(),  # pylint: disable=protected-access
            "/tmp/legacy.db",
        )

        no_basedir_gateway = _new_gateway(
            config=_make_config(
                legacy_import_enabled=True,
                legacy_import_dbm_path="relative-only.db",
                basedir=None,
            ),
            logger=logger,
        )
        self.assertTrue(
            no_basedir_gateway._resolve_legacy_import_dbm_path().endswith(  # pylint: disable=protected-access
                "relative-only.db"
            )
        )

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

    def test_read_dbm_entries_and_lock_id(self) -> None:
        class _FakeDB:
            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):  # noqa: ARG002
                return False

            def keys(self):
                return [b"alpha", b"bin", b"", "bad", b"\xff"]

            def __getitem__(self, key):
                if key == b"alpha":
                    return b"text"
                if key == b"bin":
                    return b"\xff"
                return b"\xff"

        with patch("mugen.core.gateway.storage.keyval.relational.dbm.gnu.open", return_value=_FakeDB()):
            rows = RelationalKeyValStorageGateway._read_dbm_entries("/tmp/db")  # pylint: disable=protected-access
        self.assertEqual(
            rows,
            [("alpha", b"text", "text/utf-8"), ("bin", b"\xff", "bytes")],
        )
        self.assertIsInstance(
            RelationalKeyValStorageGateway._legacy_import_lock_id("abc"),  # pylint: disable=protected-access
            int,
        )

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

    def test_sync_compatibility_methods(self) -> None:
        gateway = _new_gateway()
        gateway._run_sync = lambda awaitable: asyncio.run(awaitable)  # pylint: disable=protected-access
        gateway._list_limit_default = 1  # pylint: disable=protected-access

        gateway.put("k1", "v1")
        gateway.put("k2", b"v2")

        self.assertEqual(gateway.get("k1"), "v1")
        self.assertEqual(gateway.get("k2", decode=False), b"v2")
        self.assertIsNone(gateway.get("missing"))
        self.assertTrue(gateway.has_key("k1"))
        self.assertIn("k1", gateway.keys())
        self.assertIn("k2", gateway.keys())
        self.assertEqual(gateway.remove("k1"), b"v1")
        self.assertIsNone(gateway.remove("missing"))

        page_a = KeyValListPage(keys=["a"], next_cursor="a")
        page_b = KeyValListPage(keys=["b"], next_cursor="a")
        pages = iter([page_a, page_b])

        def _consume(awaitable):
            close = getattr(awaitable, "close", None)
            if callable(close):
                close()
            return next(pages)

        gateway._run_sync = _consume  # pylint: disable=protected-access
        self.assertEqual(gateway.keys(), ["a", "b"])

    def test_close_sync_path(self) -> None:
        gateway = _new_gateway()
        gateway._stop_sync_loop = Mock()  # pylint: disable=protected-access
        gateway._run_sync = lambda awaitable: asyncio.run(awaitable)  # pylint: disable=protected-access
        gateway.close()
        self.assertTrue(gateway._closed)  # pylint: disable=protected-access
        gateway._stop_sync_loop.assert_called_once()  # pylint: disable=protected-access
