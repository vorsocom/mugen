"""Unit tests for keyval contract defaults and keyval model helpers."""

from __future__ import annotations

from datetime import timezone
import unittest
from unittest.mock import AsyncMock, Mock

from mugen.core.contract.gateway.storage.keyval import (
    IKeyValStorageGateway,
    KeyValBackendError,
    KeyValConflictError,
)
from mugen.core.contract.gateway.storage.keyval_model import (
    KeyValConflictError as ModelConflictError,
    KeyValEntry,
    KeyValListPage,
)


class _MemoryKeyValGateway(IKeyValStorageGateway):
    def __init__(self) -> None:
        self.storage: dict[str, str | bytes | int] = {}
        self.closed = False

    def close(self) -> None:
        self.closed = True

    def get(self, key: str, decode: bool = True) -> str | bytes | None:
        value = self.storage.get(key)
        if value is None:
            return None
        if isinstance(value, bytes) and decode:
            try:
                return value.decode("utf-8")
            except UnicodeDecodeError:
                return None
        if isinstance(value, int):
            return str(value)
        return value

    def has_key(self, key: str) -> bool:
        return key in self.storage

    def keys(self) -> list[str]:
        return list(self.storage.keys())

    def put(self, key: str, value: str | bytes) -> None:
        self.storage[key] = value

    def remove(self, key: str) -> str | bytes | None:
        value = self.storage.get(key)
        if value is None:
            return None
        del self.storage[key]
        if isinstance(value, int):
            return str(value)
        return value


class TestMugenContractGatewayStorageKeyval(unittest.IsolatedAsyncioTestCase):
    """Covers async helper defaults on the keyval storage contract."""

    async def test_aclose_and_entry_read_paths(self) -> None:
        gateway = _MemoryKeyValGateway()
        gateway.storage["bytes"] = b"\xff\x00"
        gateway.storage["text"] = "hello"
        gateway.storage["other"] = 123

        bytes_entry = await gateway.get_entry("bytes", namespace="ns")
        text_entry = await gateway.get_entry("text")
        other_entry = await gateway.get_entry("other")
        missing = await gateway.get_entry("missing")

        self.assertIsNotNone(bytes_entry)
        self.assertEqual(bytes_entry.namespace, "ns")
        self.assertEqual(bytes_entry.codec, "bytes")
        self.assertEqual(text_entry.codec, "text/utf-8")
        self.assertEqual(other_entry.payload, b"123")
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

    async def test_delete_bytes_entry_and_list_negative_limit(self) -> None:
        gateway = _MemoryKeyValGateway()
        gateway.storage["bin"] = b"\x01\x02"

        removed = await gateway.delete("bin")
        self.assertIsNotNone(removed)
        self.assertEqual(removed.codec, "bytes")

        gateway.storage = {"a": "1", "b": "2"}
        page = await gateway.list_keys(limit=-10)
        self.assertEqual(len(page.keys), 1)

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
            await gateway.delete("cas", expected_row_version=1)

        updated_text = await gateway.compare_and_set(
            "cas",
            b"text",
            codec="text/utf-8",
            expected_row_version=1,
            ttl_seconds=0,
        )
        self.assertEqual(updated_text.row_version, 2)

    async def test_put_bytes_routes_to_compare_and_set_and_backend_error(self) -> None:
        gateway = _MemoryKeyValGateway()

        expected_entry = KeyValEntry(
            namespace="default",
            key="x",
            payload=b"y",
            codec="bytes",
            row_version=2,
        )
        gateway.compare_and_set = AsyncMock(return_value=expected_entry)
        result = await gateway.put_bytes("x", b"y", expected_row_version=1)
        self.assertEqual(result, expected_entry)
        gateway.compare_and_set.assert_awaited_once()

        gateway.compare_and_set = IKeyValStorageGateway.compare_and_set.__get__(gateway)
        gateway.get_entry = AsyncMock(return_value=None)
        with self.assertRaises(KeyValBackendError):
            await gateway.put_bytes("missing-verify", b"z")

        gateway.get_entry = AsyncMock(
            side_effect=[
                KeyValEntry(
                    namespace="default",
                    key="cas-fail",
                    payload=b"v1",
                    codec="bytes",
                    row_version=1,
                ),
                None,
            ]
        )
        with self.assertRaises(KeyValBackendError):
            await gateway.compare_and_set(
                "cas-fail",
                b"v2",
                expected_row_version=1,
            )

    async def test_list_keys_pagination_and_cursor_edges(self) -> None:
        gateway = _MemoryKeyValGateway()
        gateway.storage = {
            "pref:a": "1",
            "pref:b": "2",
            "pref:c": "3",
            "other": "4",
        }

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

    async def test_get_entry_handles_non_string_non_bytes_payload(self) -> None:
        gateway = _MemoryKeyValGateway()
        gateway.get = Mock(return_value=object())  # type: ignore[assignment]

        entry = await gateway.get_entry("obj")
        self.assertIsNotNone(entry)
        self.assertEqual(entry.codec, "text/utf-8")


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
