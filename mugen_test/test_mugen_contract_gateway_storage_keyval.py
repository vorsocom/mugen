"""Unit tests for async keyval contract helpers and keyval model helpers."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
import unittest

from mugen.core.contract.gateway.storage.keyval import (
    IKeyValStorageGateway,
    KeyValConflictError,
)
from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValConflictError as ModelConflictError,
    KeyValEntry,
    KeyValListPage,
)


class _MemoryKeyValGateway(IKeyValStorageGateway):
    def __init__(self) -> None:
        self.storage: dict[str, KeyValEntry] = {}
        self.closed = False

    async def aclose(self) -> None:
        self.closed = True

    async def check_readiness(self) -> None:
        if self.closed:
            raise RuntimeError("gateway closed")

    async def get_entry(
        self,
        key: str,
        *,
        namespace: str | None = None,
        include_expired: bool = False,
    ) -> KeyValEntry | None:
        target_key = str(key)
        entry = self.storage.get(target_key)
        if entry is None:
            return None
        if include_expired is True:
            return entry
        if entry.expires_at is not None and entry.expires_at <= datetime.now(timezone.utc):
            return None
        return entry

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
        if expected_row_version is not None:
            return await self.compare_and_set(
                key,
                value,
                namespace=namespace,
                codec=codec,
                expected_row_version=expected_row_version,
                ttl_seconds=ttl_seconds,
            )

        target_key = str(key)
        existing = await self.get_entry(
            target_key,
            namespace=namespace,
            include_expired=True,
        )
        row_version = 1 if existing is None else int(existing.row_version) + 1
        now = datetime.now(timezone.utc)
        expires_at = None
        if ttl_seconds is not None and float(ttl_seconds) > 0:
            expires_at = now + timedelta(seconds=float(ttl_seconds))

        entry = KeyValEntry(
            namespace=namespace or "default",
            key=target_key,
            payload=value,
            codec=codec,
            row_version=row_version,
            expires_at=expires_at,
            created_at=(None if existing is None else existing.created_at),
            updated_at=now,
        )
        self.storage[target_key] = entry
        return entry

    async def delete(
        self,
        key: str,
        *,
        namespace: str | None = None,
        expected_row_version: int | None = None,
    ) -> KeyValEntry | None:
        target_key = str(key)
        existing = await self.get_entry(
            target_key,
            namespace=namespace,
            include_expired=True,
        )
        if existing is None:
            return None

        if expected_row_version is not None and int(existing.row_version) != int(
            expected_row_version
        ):
            raise KeyValConflictError(
                namespace=namespace or "default",
                key=target_key,
                expected_row_version=int(expected_row_version),
                current_row_version=int(existing.row_version),
            )

        del self.storage[target_key]
        return existing

    async def exists(
        self,
        key: str,
        *,
        namespace: str | None = None,
    ) -> bool:
        entry = await self.get_entry(key, namespace=namespace)
        return entry is not None

    async def list_keys(
        self,
        *,
        prefix: str = "",
        namespace: str | None = None,
        limit: int | None = None,
        cursor: str | None = None,
    ) -> KeyValListPage:
        del namespace
        eligible = []
        for key in sorted(self.storage.keys()):
            if key.startswith(prefix) is not True:
                continue
            entry = await self.get_entry(key)
            if entry is None:
                continue
            eligible.append(key)

        if cursor not in [None, ""]:
            eligible = [item for item in eligible if item > str(cursor)]

        page_limit = int(limit or len(eligible) or 1)
        if page_limit <= 0:
            page_limit = 1

        keys = eligible[:page_limit]
        next_cursor = keys[-1] if len(eligible) > page_limit and keys else None
        return KeyValListPage(keys=keys, next_cursor=next_cursor)

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
        target_key = str(key)
        current = await self.get_entry(
            target_key,
            namespace=namespace,
            include_expired=True,
        )
        current_row_version = 0 if current is None else int(current.row_version)
        if current_row_version != int(expected_row_version):
            raise KeyValConflictError(
                namespace=namespace or "default",
                key=target_key,
                expected_row_version=int(expected_row_version),
                current_row_version=current_row_version,
            )
        return await self.put_bytes(
            target_key,
            value,
            namespace=namespace,
            codec=codec,
            expected_row_version=None,
            ttl_seconds=ttl_seconds,
        )


class TestMugenContractGatewayStorageKeyval(unittest.IsolatedAsyncioTestCase):
    """Covers async helper defaults on the keyval storage contract."""

    async def test_aclose_and_entry_read_paths(self) -> None:
        gateway = _MemoryKeyValGateway()
        gateway.storage["bytes"] = KeyValEntry(
            namespace="default",
            key="bytes",
            payload=b"\xff\x00",
            codec="bytes",
            row_version=1,
        )
        gateway.storage["text"] = KeyValEntry(
            namespace="default",
            key="text",
            payload=b"hello",
            codec="text/utf-8",
            row_version=1,
        )

        bytes_entry = await gateway.get_entry("bytes", namespace="ns")
        text_entry = await gateway.get_entry("text")
        missing = await gateway.get_entry("missing")

        self.assertIsNotNone(bytes_entry)
        self.assertEqual(bytes_entry.codec, "bytes")
        self.assertEqual(text_entry.codec, "text/utf-8")
        self.assertIsNone(missing)

        await gateway.aclose()
        self.assertTrue(gateway.closed)

    async def test_get_text_get_json_put_text_put_json_exists_and_delete(self) -> None:
        gateway = _MemoryKeyValGateway()

        await gateway.put_text("k1", "value")
        await gateway.put_json("k2", {"a": 1})
        self.assertEqual(await gateway.get_text("k1"), "value")
        self.assertEqual(await gateway.get_json("k2"), {"a": 1})
        self.assertTrue(await gateway.exists("k1"))

        removed = await gateway.delete("k1")
        self.assertIsNotNone(removed)
        self.assertEqual(removed.key, "k1")
        self.assertIsNone(await gateway.delete("k1"))
        self.assertIsNone(await gateway.get_text("missing"))
        self.assertIsNone(await gateway.get_json("missing"))

    async def test_put_bytes_compare_and_set_and_conflict_paths(self) -> None:
        gateway = _MemoryKeyValGateway()

        created = await gateway.compare_and_set(
            "cas",
            b"one",
            expected_row_version=0,
            ttl_seconds=2.0,
        )
        self.assertEqual(created.row_version, 1)
        self.assertIsNotNone(created.expires_at)
        self.assertEqual(created.expires_at.tzinfo, timezone.utc)

        with self.assertRaises(KeyValConflictError):
            await gateway.compare_and_set(
                "cas",
                b"two",
                expected_row_version=2,
            )

        with self.assertRaises(KeyValConflictError):
            await gateway.delete("cas", expected_row_version=2)

        updated_text = await gateway.compare_and_set(
            "cas",
            b"text",
            codec="text/utf-8",
            expected_row_version=1,
            ttl_seconds=0,
        )
        self.assertEqual(updated_text.row_version, 2)

    async def test_list_keys_pagination_and_cursor_edges(self) -> None:
        gateway = _MemoryKeyValGateway()
        await gateway.put_text("pref:a", "1")
        await gateway.put_text("pref:b", "2")
        await gateway.put_text("pref:c", "3")
        await gateway.put_text("other", "4")

        page1 = await gateway.list_keys(prefix="pref:", limit=2)
        page2 = await gateway.list_keys(prefix="pref:", limit=2, cursor=page1.next_cursor)
        empty = await gateway.list_keys(prefix="pref:", cursor="zzz")
        coerced_limit = await gateway.list_keys(prefix="pref:", limit=0)

        self.assertEqual(page1.keys, ["pref:a", "pref:b"])
        self.assertEqual(page1.next_cursor, "pref:b")
        self.assertEqual(page2.keys, ["pref:c"])
        self.assertIsNone(page2.next_cursor)
        self.assertEqual(empty.keys, [])
        self.assertIsNone(empty.next_cursor)
        self.assertEqual(len(coerced_limit.keys), 3)


class TestMugenContractGatewayStorageKeyvalModel(unittest.TestCase):
    """Covers keyval model decode helpers and typed errors."""

    def test_conflict_error_fields_and_message(self) -> None:
        err = ModelConflictError(
            namespace="core",
            key="k1",
            expected_row_version=3,
            current_row_version=2,
        )
        self.assertEqual(err.namespace, "core")
        self.assertEqual(err.key, "k1")
        self.assertEqual(err.expected_row_version, 3)
        self.assertEqual(err.current_row_version, 2)
        self.assertIn("expected_row_version=3", str(err))

    def test_entry_text_and_json_decode_paths(self) -> None:
        valid_json = KeyValEntry(
            namespace="core",
            key="k",
            payload=b'{"x":[1,2]}',
            codec="application/json",
            row_version=1,
        )
        valid_list = KeyValEntry(
            namespace="core",
            key="k2",
            payload=b"[1,2,3]",
            codec="application/json",
            row_version=1,
        )
        invalid_utf8 = KeyValEntry(
            namespace="core",
            key="k3",
            payload=b"\xff",
            codec="bytes",
            row_version=1,
        )
        scalar_json = KeyValEntry(
            namespace="core",
            key="k4",
            payload=b'"scalar"',
            codec="application/json",
            row_version=1,
        )

        self.assertEqual(valid_json.as_text(), '{"x":[1,2]}')
        self.assertEqual(valid_json.as_json(), {"x": [1, 2]})
        self.assertEqual(valid_list.as_json(), [1, 2, 3])
        self.assertIsNone(invalid_utf8.as_text())
        self.assertIsNone(invalid_utf8.as_json())
        self.assertIsNone(scalar_json.as_json())

    def test_list_page_model(self) -> None:
        page = KeyValListPage(keys=["a", "b"], next_cursor="b")
        self.assertEqual(page.keys, ["a", "b"])
        self.assertEqual(page.next_cursor, "b")
